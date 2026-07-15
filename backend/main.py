import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.clip_selector import select_clips
from backend.services.youtube_downloader import (
    download_youtube_video,
    get_video_info,
    validate_youtube_url,
)
from backend.subtitle_generator import burn_captions
from backend.transcriber import transcribe_video
from backend.utils import (
    OUTPUTS_DIR,
    UPLOADS_DIR,
    MUSIC_DIR,
    cleanup_old_files,
    ensure_dirs,
    get_video_duration,
)
from backend.video_processor import (
    apply_copyright_safe,
    apply_visual_cleanup,
    convert_to_shorts,
    create_zip,
    cut_clip,
    mix_background_music,
    normalize_audio,
    overlay_logo,
)

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    cleanup_old_files(UPLOADS_DIR)
    cleanup_old_files(OUTPUTS_DIR)
    yield


app = FastAPI(title="VideoClipper AI", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscribeRequest(BaseModel):
    job_id: str
    file_path: str


class SelectClipsRequest(BaseModel):
    job_id: str
    transcript_data: dict
    video_duration: float
    num_clips: int = 5
    min_length: float = 20.0
    max_length: float = 150.0


class ProcessOptions(BaseModel):
    shorts_format: bool = False
    burn_subtitles: bool = False
    add_music: bool = False
    normalize_audio: bool = False
    visual_cleanup: bool = False
    cleanup_position: str = "top_left"
    music_volume: float = 0.12
    music_path: Optional[str] = None
    copyright_safe: bool = False
    mirror: bool = False
    add_logo: bool = False
    logo_path: Optional[str] = None


class ClipInput(BaseModel):
    clip_number: int
    start_time: float
    end_time: float
    title: str = "Clip"
    reason: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    virality_score: int = 60
    hook_score: int = 60
    content_score: int = 60
    include: bool = True


class ProcessClipsRequest(BaseModel):
    job_id: str
    file_path: str
    clips: list[ClipInput]
    transcript_data: dict = Field(default_factory=dict)
    options: ProcessOptions = Field(default_factory=ProcessOptions)


class DownloadZipRequest(BaseModel):
    job_id: str
    clip_paths: list[str]


class YouTubeUrlRequest(BaseModel):
    url: str


def _schedule_cleanup(background_tasks: BackgroundTasks) -> None:
    background_tasks.add_task(cleanup_old_files, UPLOADS_DIR)
    background_tasks.add_task(cleanup_old_files, OUTPUTS_DIR)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/youtube-info")
def youtube_info(request: YouTubeUrlRequest) -> dict:
    valid, message = validate_youtube_url(request.url)
    if not valid:
        raise HTTPException(status_code=400, detail=message)

    try:
        return get_video_info(request.url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/download-youtube")
def download_youtube(
    request: YouTubeUrlRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    valid, message = validate_youtube_url(request.url)
    if not valid:
        raise HTTPException(status_code=400, detail=message)

    try:
        ensure_dirs()
        job_id = str(uuid.uuid4())
        staging_dir = UPLOADS_DIR / f"{job_id}_youtube"
        downloaded = Path(download_youtube_video(request.url, str(staging_dir)))

        dest = UPLOADS_DIR / f"{job_id}.mp4"
        if dest.exists():
            dest.unlink()
        shutil.move(str(downloaded), str(dest))
        shutil.rmtree(staging_dir, ignore_errors=True)

        duration = get_video_duration(dest)
        info = get_video_info(request.url)
        _schedule_cleanup(background_tasks)

        return {
            "job_id": job_id,
            "filename": dest.name,
            "duration": duration,
            "file_path": str(dest),
            "source": "youtube",
            "source_url": request.url,
            "title": info.get("title", "YouTube video"),
            "uploader": info.get("uploader", "Unknown"),
            "view_count": info.get("view_count", 0),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict:
    try:
        ensure_dirs()
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")

        ext = Path(file.filename).suffix.lower()
        audio_exts = {".mp3", ".wav", ".m4a"}
        image_exts = {".png", ".jpg", ".jpeg", ".webp"}
        video_exts = {".mp4", ".mov", ".mkv", ".avi"}
        allowed = video_exts | audio_exts | image_exts
        if ext not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(allowed))}",
            )

        job_id = str(uuid.uuid4())
        unique_name = f"{job_id}{ext}"

        if ext in audio_exts:
            dest = MUSIC_DIR / unique_name
        else:
            dest = UPLOADS_DIR / unique_name

        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)

        duration = 0.0
        if ext in video_exts:
            duration = get_video_duration(dest)

        if background_tasks:
            _schedule_cleanup(background_tasks)

        return {
            "job_id": job_id,
            "filename": unique_name,
            "duration": duration,
            "file_path": str(dest),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/transcribe")
def transcribe(
    request: TranscribeRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    try:
        if not Path(request.file_path).exists():
            raise HTTPException(status_code=404, detail="Video file not found")

        result = transcribe_video(request.file_path)
        _schedule_cleanup(background_tasks)
        return {
            "job_id": request.job_id,
            "transcript": result["full_text"],
            "segments": result["segments"],
            "words": result["words"],
            "transcript_data": result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/select-clips")
def select_clips_endpoint(
    request: SelectClipsRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    try:
        clips = select_clips(
            request.transcript_data,
            request.video_duration,
            num_clips=request.num_clips,
            min_length=request.min_length,
            max_length=request.max_length,
        )
        _schedule_cleanup(background_tasks)
        return {"job_id": request.job_id, "clips": clips}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/process-clips")
def process_clips(
    request: ProcessClipsRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    try:
        source = Path(request.file_path)
        if not source.exists():
            raise HTTPException(status_code=404, detail="Source video not found")

        job_output_dir = OUTPUTS_DIR / request.job_id
        job_output_dir.mkdir(parents=True, exist_ok=True)

        included = [c for c in request.clips if c.include]
        if not included:
            raise HTTPException(status_code=400, detail="No clips selected for processing")

        processed: list[dict[str, Any]] = []

        for clip in included:
            safe_title = "".join(
                ch if ch.isalnum() or ch in (" ", "-", "_") else "_"
                for ch in clip.title
            ).strip().replace(" ", "_")[:40] or f"clip_{clip.clip_number}"

            base_name = f"clip_{clip.clip_number}_{safe_title}.mp4"
            current_path = job_output_dir / base_name

            want_captions = request.options.burn_subtitles and bool(
                request.transcript_data
            )

            # Frame-accurate cut when we need captions so they stay in sync.
            cut_clip(
                str(source),
                clip.start_time,
                clip.end_time,
                str(current_path),
                precise=want_captions,
            )

            # Copyright-safe transforms run before captions/logo so a mirror
            # flip never reverses burned text or the overlaid logo.
            if request.options.copyright_safe or request.options.mirror:
                safe_out = job_output_dir / f"safe_{current_path.name}"
                current_path = Path(
                    apply_copyright_safe(
                        str(current_path),
                        str(safe_out),
                        mirror=request.options.mirror,
                    )
                )

            if request.options.shorts_format:
                shorts_path = job_output_dir / f"shorts_{base_name}"
                current_path = Path(
                    convert_to_shorts(str(current_path), str(shorts_path))
                )

            if request.options.visual_cleanup:
                cleanup_out = job_output_dir / f"clean_{current_path.name}"
                current_path = Path(
                    apply_visual_cleanup(
                        str(current_path),
                        str(cleanup_out),
                        position=request.options.cleanup_position,
                    )
                )

            if (
                request.options.add_logo
                and request.options.logo_path
                and Path(request.options.logo_path).exists()
            ):
                logo_out = job_output_dir / f"logo_{current_path.name}"
                current_path = Path(
                    overlay_logo(
                        str(current_path),
                        request.options.logo_path,
                        str(logo_out),
                        position=request.options.cleanup_position,
                    )
                )

            if want_captions:
                captioned_path = job_output_dir / f"captioned_{current_path.name}"
                current_path = Path(
                    burn_captions(
                        str(current_path),
                        request.transcript_data,
                        str(captioned_path),
                        clip_start=clip.start_time,
                        clip_end=clip.end_time,
                    )
                )

            if (
                request.options.add_music
                and request.options.music_path
                and Path(request.options.music_path).exists()
            ):
                music_out = job_output_dir / f"music_{current_path.name}"
                current_path = Path(
                    mix_background_music(
                        str(current_path),
                        request.options.music_path,
                        str(music_out),
                        music_volume=request.options.music_volume,
                    )
                )

            if request.options.normalize_audio:
                normalized_out = job_output_dir / f"normalized_{current_path.name}"
                current_path = Path(
                    normalize_audio(str(current_path), str(normalized_out))
                )

            processed.append(
                {
                    "clip_number": clip.clip_number,
                    "title": clip.title,
                    "description": clip.description,
                    "hashtags": clip.hashtags,
                    "virality_score": clip.virality_score,
                    "hook_score": clip.hook_score,
                    "content_score": clip.content_score,
                    "output_path": str(current_path),
                    "filename": current_path.name,
                }
            )

        _schedule_cleanup(background_tasks)
        return {"job_id": request.job_id, "processed_clips": processed}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/download-zip")
def download_zip(
    request: DownloadZipRequest,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    try:
        zip_name = f"{request.job_id}_clips.zip"
        zip_path = OUTPUTS_DIR / zip_name
        create_zip(request.clip_paths, str(zip_path))

        if not zip_path.exists():
            raise HTTPException(status_code=500, detail="Failed to create ZIP file")

        _schedule_cleanup(background_tasks)
        return FileResponse(
            path=str(zip_path),
            filename=zip_name,
            media_type="application/zip",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/download/{filename}")
def download_file(
    filename: str,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    try:
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        outputs_root = OUTPUTS_DIR.resolve()
        file_path = (OUTPUTS_DIR / safe_name).resolve()
        if not file_path.exists():
            for sub in OUTPUTS_DIR.iterdir():
                if sub.is_dir():
                    candidate = (sub / safe_name).resolve()
                    if candidate.exists():
                        file_path = candidate
                        break

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if outputs_root not in file_path.parents and file_path != outputs_root:
            raise HTTPException(status_code=400, detail="Invalid file path")

        _schedule_cleanup(background_tasks)
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/octet-stream",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/preview-upload/{filename}")
def preview_upload(filename: str) -> FileResponse:
    """Serve the uploaded source video for browser preview/seek."""
    try:
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        uploads_root = UPLOADS_DIR.resolve()
        file_path = (UPLOADS_DIR / safe_name).resolve()
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Uploaded video not found")
        if uploads_root not in file_path.parents and file_path != uploads_root:
            raise HTTPException(status_code=400, detail="Invalid file path")

        return FileResponse(
            path=str(file_path),
            filename=safe_name,
            media_type="video/mp4",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
