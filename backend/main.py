"""
FastAPI backend entrypoint for VideoClipper.
Wires upload handling, background pipeline, job APIs, and app lifecycle.
"""

import logging
import pathlib
import subprocess
import uuid
import time
import sys
from pathlib import Path
from typing import Dict


if __package__ in (None, ""):
	project_root = Path(__file__).resolve().parent.parent
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	__package__ = "backend"

import uvicorn
from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import config

from .jobs import job_store
from .jobs.job_store import create_job, get_job, mark_done, mark_error, update_job
from .models.schemas import JobStatus, ProcessResponse
from .services.analyzer import analyze_transcript, score_clips
from .services.audio_extractor import extract_audio
from .services.clipper import cut_all_shorts, cut_clips
from .services.transcriber import transcribe_audio, get_supported_languages
from .services.youtube_downloader import (
	download_youtube_video,
	get_video_info,
	validate_youtube_url,
)
from .utils.file_manager import cleanup_job_folder, create_job_folder, get_job_path
from .utils.validators import validate_video_file
from .services.video_preview import get_full_video_preview, generate_preview_thumbnail
from .services.cleanup_scheduler import start_cleanup_scheduler, stop_cleanup_scheduler


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Create FastAPI app with configured CORS
app = FastAPI(title="VideoClipper API", version="2.0.0")
allowed = [o.strip() for o in str(config.ALLOWED_ORIGINS).split(",") if o.strip()]
if not allowed:
	allowed = ["*"]
app.add_middleware(
	CORSMiddleware,
	allow_origins=allowed,
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
	if isinstance(exc.detail, dict) and "detail" in exc.detail and "error_code" in exc.detail:
		payload = exc.detail
	else:
		payload = {"detail": str(exc.detail), "error_code": "HTTP_ERROR"}
	return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
	return JSONResponse(status_code=422, content={"detail": "Invalid request parameters", "error_code": "VALIDATION_ERROR"})


@app.middleware("http")
async def log_requests(request: Request, call_next):
	start_time = time.time()
	response = await call_next(request)
	duration = time.time() - start_time
	logger.info(f"{request.method} {request.url.path} — {response.status_code} — {duration:.2f}s")
	return response


@app.on_event("startup")
def startup_event() -> None:
	"""Initialize required directories and background services."""
	try:
		pathlib.Path(config.TEMP_DIR).mkdir(parents=True, exist_ok=True)
		pathlib.Path(config.MUSIC_DIR).mkdir(parents=True, exist_ok=True)
		app.state.scheduler = start_cleanup_scheduler()
		logger.info("Application started and scheduler initialized")
	except Exception:
		logger.exception("Failed to start application services on startup")


@app.on_event("shutdown")
def shutdown_event() -> None:
	"""Stop background services and mark interrupted jobs as errors."""
	try:
		# Stop scheduler
		if hasattr(app.state, "scheduler"):
			stop_cleanup_scheduler(app.state.scheduler)

		# Mark any processing/downloading jobs as interrupted errors
		interrupted: Dict[str, dict] = {}
		with job_store._jobs_lock:
			for jid, jdata in job_store.jobs.items():
				if jdata.get("status") in {"processing", "transcribing", "cutting", "downloading", "extracting_audio", "analyzing"}:
					jdata["status"] = "error"
					jdata["error"] = "Server shutting down: job interrupted"
					jdata["current_step"] = "Interrupted by shutdown"
					jdata["message"] = "Interrupted by shutdown"
					interrupted[jid] = jdata

		if interrupted:
			logger.warning("Marked %d jobs as interrupted during shutdown: %s", len(interrupted), list(interrupted.keys()))
	except Exception:
		logger.exception("Error during shutdown handling")


def _set_job_metadata(job_id: str, **fields: object) -> None:
	"""Safely persist extra metadata fields directly in the in-memory job store."""
	try:
		with job_store._jobs_lock:
			if job_id in job_store.jobs:
				job_store.jobs[job_id].update(fields)
	except Exception:
		logger.exception("Failed to update job metadata for job %s", job_id)


def run_pipeline_from_video(
	job_id: str,
	video_path: str,
	job_folder: str,
	guidance: str,
	generate_shorts: bool,
	language: str = "en",
) -> None:
	"""Execute shared processing pipeline for a local video file."""
	logger.info("Pipeline started for job %s", job_id)

	def fail_job(error: Exception) -> None:
		try:
			mark_error(job_id, str(error))
		finally:
			try:
				cleanup_job_folder(job_id)
			except Exception:
				logger.exception("Cleanup failed for job %s after an error", job_id)

	job_snapshot = get_job(job_id) or {}
	started_from_youtube = job_snapshot.get("status") == "downloading"
	step_offset = 1 if started_from_youtube else 0
	step_total = (6 if generate_shorts else 5) if started_from_youtube else (5 if generate_shorts else 4)

	# Step 1: extract audio
	try:
		update_job(job_id, "extracting_audio", f"Extracting audio (Step {1 + step_offset} of {step_total})...", 20)
		audio_path = extract_audio(video_path, str(pathlib.Path(job_folder) / "audio.mp3"))
	except Exception as exc:
		logger.exception("Audio extraction failed for job %s", job_id)
		fail_job(exc)
		return

	# Step 2: transcribe
	try:
		update_job(job_id, "transcribing", f"Transcribing audio (Step {2 + step_offset} of {step_total})...", 45)
		segments = transcribe_audio(audio_path, language=language)
	except Exception as exc:
		logger.exception("Transcription failed for job %s", job_id)
		fail_job(exc)
		return

	# Step 3: analyze transcript
	try:
		update_job(job_id, "analyzing", f"Analyzing content (Step {3 + step_offset} of {step_total})...", 65)
		clips, music_style = analyze_transcript(segments, guidance or None)
		clips = score_clips(clips, segments)
		_set_job_metadata(job_id, music_style=music_style)
	except Exception as exc:
		logger.exception("Transcript analysis failed for job %s", job_id)
		fail_job(exc)
		return

	# Step 4: cut clips
	try:
		update_job(job_id, "cutting", f"Cutting clips (Step {4 + step_offset} of {step_total})...", 85)
		clip_results = cut_clips(video_path, clips, job_folder, all_segments=segments, music_style=music_style, is_shorts=False)
	except Exception as exc:
		logger.exception("Clip cutting failed for job %s", job_id)
		fail_job(exc)
		return

	# Step 5: shorts (optional)
	shorts_clips = []
	if generate_shorts:
		update_job(job_id, "creating_shorts", f"Creating Shorts versions (Step {5 + step_offset} of {step_total})...", 92)
		try:
			shorts_clips = cut_all_shorts(video_path, clips, job_folder, all_segments=segments, music_style=music_style)
			logger.info("Job %s: %d shorts clips created", job_id, len(shorts_clips))
		except Exception as e:
			logger.warning("Job %s: Shorts generation failed: %s", job_id, e)
			shorts_clips = []

	mark_done(job_id, clip_results)

	# Titles/metadata (non-critical)
	try:
		from .services.title_generator import generate_all_metadata

		clip_results = generate_all_metadata(clip_results, segments)
		job = get_job(job_id)
		if job:
			job["clips"] = clip_results
		logger.info("Job %s: Metadata generation complete", job_id)
	except Exception as e:
		logger.warning("Job %s: Metadata generation failed (non-critical): %s", job_id, e)

	# Viral scoring (non-critical)
	try:
		from .services.viral_scorer import score_all_clips

		clip_results = score_all_clips(clip_results, segments, use_llm=True)
		job = get_job(job_id)
		if job:
			job["clips"] = clip_results
		logger.info("Job %s: Viral scoring complete", job_id)
	except Exception as e:
		logger.warning("Job %s: Viral scoring failed (non-critical): %s", job_id, e)

	# Chapter detection (non-critical)
	try:
		from .services.chapter_detector import detect_chapters, format_chapters_for_youtube

		video_duration = segments[-1]["end"] if segments else 0
		chapters = detect_chapters(segments, video_duration)
		youtube_chapters = format_chapters_for_youtube(chapters)
		job = get_job(job_id)
		if job:
			job["chapters"] = chapters
			job["youtube_chapters"] = youtube_chapters
		logger.info("Job %s: Chapter detection complete — %d chapters", job_id, len(chapters))
	except Exception as e:
		logger.warning("Job %s: Chapter detection failed (non-critical): %s", job_id, e)

	_set_job_metadata(job_id, shorts_clips=shorts_clips, music_style=music_style)
	logger.info("Pipeline complete for job %s", job_id)


def run_pipeline(job_id: str, video_path: str, guidance: str, generate_shorts: bool = False, language: str = "en") -> None:
	job_folder = get_job_path(job_id)
	run_pipeline_from_video(job_id, video_path, job_folder, guidance, generate_shorts, language=language)


def run_youtube_pipeline(job_id: str, youtube_url: str, job_folder: str, guidance: str, generate_shorts: bool) -> None:
	total_steps = 6 if generate_shorts else 5
	try:
		update_job(job_id, "downloading", f"Downloading YouTube video (Step 0 of {total_steps})...", 5)
		video_path = download_youtube_video(youtube_url, job_folder)
		logger.info("Job %s: Downloaded to %s", job_id, video_path)
	except Exception as e:
		mark_error(job_id, f"Download failed: {str(e)}")
		return

	run_pipeline_from_video(job_id, video_path, job_folder, guidance, generate_shorts)


@app.post("/process", response_model=ProcessResponse)
async def process_video(
	background_tasks: BackgroundTasks,
	video: UploadFile = File(...),
	guidance: str = Form(default="", max_length=500),
	shorts_mode: str = Form(default="false"),
	language: str = Form(default="en"),
) -> ProcessResponse:
	logger.info("Received POST /process request for filename=%s", getattr(video, "filename", ""))
	try:
		file_content = await video.read()
		filename = video.filename or ""

		is_valid, error_message = validate_video_file(filename, len(file_content))
		if not is_valid:
			raise HTTPException(status_code=400, detail={"detail": error_message, "error_code": "INVALID_FILE"})

		clean_guidance = (guidance or "").strip()
		if len(clean_guidance) > 500:
			clean_guidance = clean_guidance[:500]

		generate_shorts = shorts_mode.lower() == "true"

		job_id = str(uuid.uuid4())
		create_job(job_id)
		job_folder = create_job_folder(job_id)

		file_extension = pathlib.Path(filename).suffix or ".mp4"
		video_path = pathlib.Path(job_folder) / f"video{file_extension}"

		with open(video_path, "wb") as output_file:
			output_file.write(file_content)

		background_tasks.add_task(run_pipeline, job_id, str(video_path), clean_guidance, generate_shorts, language)

		return ProcessResponse(job_id=job_id, message="Processing started")
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to start processing job")
		raise HTTPException(status_code=500, detail={"detail": "Failed to start job", "error_code": "START_FAILED"}) from exc


@app.post("/process-url", response_model=ProcessResponse)
async def process_url(
	background_tasks: BackgroundTasks,
	youtube_url: str = Form(...),
	guidance: str = Form(default=""),
	shorts_mode: str = Form(default="false"),
) -> ProcessResponse:
	logger.info("Received POST /process-url request")
	try:
		if not youtube_url or len(youtube_url) > 200:
			raise HTTPException(status_code=400, detail={"detail": "Invalid or empty URL", "error_code": "INVALID_URL"})
		valid, error_msg = validate_youtube_url(youtube_url)
		if not valid:
			raise HTTPException(status_code=400, detail={"detail": error_msg, "error_code": "INVALID_URL_FORMAT"})

		clean_guidance = (guidance or "").strip()
		if len(clean_guidance) > 500:
			clean_guidance = clean_guidance[:500]

		job_id = str(uuid.uuid4())
		create_job(job_id)
		job_folder = create_job_folder(job_id)

		generate_shorts = shorts_mode.lower() == "true"

		background_tasks.add_task(run_youtube_pipeline, job_id, youtube_url, job_folder, clean_guidance, generate_shorts)

		return ProcessResponse(job_id=job_id, message="YouTube video download started")
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to start YouTube processing job")
		raise HTTPException(status_code=500, detail={"detail": "Failed to start YouTube job", "error_code": "START_FAILED"}) from exc


@app.get("/status/{job_id}", response_model=JobStatus)
def get_status(job_id: str) -> JobStatus:
	logger.info("Received GET /status/%s request", job_id)
	try:
		job = get_job(job_id)
		if job is None:
			raise HTTPException(status_code=404, detail={"detail": "Job not found", "error_code": "NOT_FOUND"})

		job_data = dict(job)
		job_data.setdefault("shorts_clips", [])
		job_data.setdefault("music_style", config.DEFAULT_MUSIC_STYLE)
		job_data.setdefault("chapters", [])
		job_data.setdefault("youtube_chapters", "")
		job_data.setdefault("message", job_data.get("current_step", ""))

		return JobStatus(**job_data)
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to fetch status for job %s", job_id)
		raise HTTPException(status_code=500, detail={"detail": "Failed to fetch status", "error_code": "STATUS_ERROR"}) from exc


@app.post("/preview-upload")
async def preview_upload(video: UploadFile = File(...)) -> dict:
	logger.info("Received POST /preview-upload filename=%s", getattr(video, "filename", ""))
	temp_path = None
	try:
		file_content = await video.read()
		filename = video.filename or ""

		is_valid, error_message = validate_video_file(filename, len(file_content))
		if not is_valid:
			raise HTTPException(status_code=400, detail={"detail": error_message, "error_code": "INVALID_FILE"})

		temp_id = str(uuid.uuid4())
		temp_path = pathlib.Path(config.TEMP_DIR) / f"preview_{temp_id}.mp4"
		temp_path.parent.mkdir(parents=True, exist_ok=True)
		with open(temp_path, "wb") as out:
			out.write(file_content)

		preview = get_full_video_preview(str(temp_path))
		return preview
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Preview generation failed")
		raise HTTPException(status_code=500, detail={"detail": "Preview failed", "error_code": "PREVIEW_FAILED"}) from exc
	finally:
		try:
			if temp_path is not None and pathlib.Path(temp_path).exists():
				pathlib.Path(temp_path).unlink()
		except Exception:
			logger.exception("Failed to delete temporary preview file %s", temp_path)


@app.get("/video-info")
async def video_info(url: str):
	if not url or not url.strip() or len(url) > 200:
		raise HTTPException(status_code=400, detail={"detail": "Invalid or empty URL", "error_code": "INVALID_URL"})
	valid, err = validate_youtube_url(url)
	if not valid:
		raise HTTPException(status_code=400, detail={"detail": err, "error_code": "INVALID_URL"})
	try:
		info = get_video_info(url)
		return info
	except Exception as e:
		logger.exception("Failed to fetch video info for %s: %s", url, e)
		raise HTTPException(status_code=500, detail={"detail": "Failed to get video info", "error_code": "VIDEO_INFO_FAILED"}) from e


def get_video_duration(video_path: str) -> float:
	try:
		logger.info("Reading video duration for %s", video_path)
		command = [
			"ffprobe",
			"-v",
			"error",
			"-show_entries",
			"format=duration",
			"-of",
			"default=noprint_wrappers=1:nokey=1",
			video_path,
		]
		result = subprocess.run(command, capture_output=True, text=True)
		if result.returncode != 0:
			logger.warning("ffprobe failed for %s: %s", video_path, result.stderr.strip())
			return 0.0
		output = result.stdout.strip()
		if not output:
			logger.warning("ffprobe returned no duration for %s", video_path)
			return 0.0
		duration = float(output)
		logger.debug("Video duration for %s: %.2f", video_path, duration)
		return duration
	except Exception as exc:
		logger.warning("Failed to read video duration for %s: %s", video_path, exc)
		return 0.0


@app.get("/filter-presets")
async def get_filter_presets():
	logger.info("Received GET /filter-presets request")
	try:
		from .services.filter_editor import get_filter_presets as _get_filter_presets

		return _get_filter_presets()
	except Exception as exc:
		logger.exception("Failed to load filter presets: %s", exc)
		raise HTTPException(status_code=500, detail={"detail": "Failed to load filter presets", "error_code": "PRESETS_ERROR"}) from exc


@app.post("/apply-filter/{job_id}/{filename}")
async def apply_filter(job_id: str, filename: str, filters: dict = Body(...)):
	logger.info("Received POST /apply-filter/%s/%s request", job_id, filename)
	try:
		job = get_job(job_id)
		if job is None:
			raise HTTPException(status_code=404, detail={"detail": "Job not found", "error_code": "NOT_FOUND"})

		if not filename.endswith(".mp4"):
			raise HTTPException(status_code=400, detail={"detail": "Invalid file format", "error_code": "BAD_FORMAT"})

		job_path = pathlib.Path(get_job_path(job_id))
		input_path = job_path / filename
		if not input_path.exists():
			raise HTTPException(status_code=404, detail={"detail": "File not found", "error_code": "NOT_FOUND"})

		from .services.filter_editor import apply_filters, validate_filters

		cleaned_filters = validate_filters(filters)
		duration = get_video_duration(str(input_path))

		output_filename = f"filtered_{filename}"
		output_path = job_path / output_filename
		apply_filters(str(input_path), str(output_path), cleaned_filters, duration)

		return {"filtered_filename": output_filename, "message": "Filter applied"}
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to apply filter for job %s and file %s", job_id, filename)
		raise HTTPException(status_code=500, detail={"detail": "Filter failed", "error_code": "FILTER_FAILED"}) from exc


@app.get("/download-filtered/{job_id}/{filename}")
def download_filtered_clip(job_id: str, filename: str) -> FileResponse:
	logger.info("Received GET /download-filtered/%s/%s request", job_id, filename)
	try:
		job = get_job(job_id)
		if job is None or job.get("status") != "done":
			raise HTTPException(status_code=404, detail={"detail": "Filtered clip not available", "error_code": "NOT_AVAILABLE"})

		if not filename.startswith("filtered_") or not filename.endswith(".mp4"):
			raise HTTPException(status_code=400, detail={"detail": "Invalid filename", "error_code": "BAD_FILENAME"})

		job_path = pathlib.Path(get_job_path(job_id))
		file_path = job_path / filename
		if not file_path.exists() or not file_path.resolve().is_relative_to(job_path.resolve()):
			raise HTTPException(status_code=404, detail={"detail": "File not found", "error_code": "NOT_FOUND"})

		return FileResponse(str(file_path), media_type="video/mp4", filename=filename)
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to download filtered clip for job %s", job_id)
		raise HTTPException(status_code=500, detail={"detail": "Download failed", "error_code": "DOWNLOAD_FAILED"}) from exc


@app.get("/languages")
def get_languages():
	try:
		return get_supported_languages()
	except Exception as exc:
		logger.exception("Failed to return supported languages: %s", exc)
		raise HTTPException(status_code=500, detail={"detail": "Failed to load languages", "error_code": "LANGUAGES_ERROR"}) from exc


@app.get("/download/{job_id}/{filename}")
def download_clip(job_id: str, filename: str) -> FileResponse:
	logger.info("Received GET /download/%s/%s request", job_id, filename)
	try:
		job = get_job(job_id)
		if job is None or job.get("status") != "done":
			raise HTTPException(status_code=404, detail={"detail": "Clip not available", "error_code": "NOT_AVAILABLE"})

		job_clips = job.get("clips") or []
		allowed_filenames = {c.get("filename") for c in job_clips if isinstance(c, dict) and c.get("filename")}
		if filename not in allowed_filenames:
			raise HTTPException(status_code=404, detail={"detail": "File not found", "error_code": "NOT_FOUND"})

		job_path = pathlib.Path(config.TEMP_DIR) / f"job_{job_id}"
		file_path = job_path / filename
		if not file_path.exists() or not file_path.resolve().is_relative_to(job_path.resolve()):
			raise HTTPException(status_code=404, detail={"detail": "File not found", "error_code": "NOT_FOUND"})

		return FileResponse(str(file_path), media_type="video/mp4", filename=filename)
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to download clip for job %s", job_id)
		raise HTTPException(status_code=500, detail={"detail": "Download failed", "error_code": "DOWNLOAD_FAILED"}) from exc


@app.get("/download-shorts/{job_id}/{filename}")
def download_shorts(job_id: str, filename: str) -> FileResponse:
	logger.info("Received GET /download-shorts/%s/%s request", job_id, filename)
	try:
		job = get_job(job_id)
		if job is None or job.get("status") != "done":
			raise HTTPException(status_code=404, detail={"detail": "Shorts clip not available", "error_code": "NOT_AVAILABLE"})

		if not filename.startswith("shorts_") or not filename.endswith(".mp4"):
			raise HTTPException(status_code=400, detail={"detail": "Invalid filename", "error_code": "BAD_FILENAME"})

		job_shorts = job.get("shorts_clips") or []
		allowed_filenames = {s.get("filename") for s in job_shorts if isinstance(s, dict) and s.get("filename")}
		if filename not in allowed_filenames:
			raise HTTPException(status_code=404, detail={"detail": "File not found", "error_code": "NOT_FOUND"})

		job_path = pathlib.Path(config.TEMP_DIR) / f"job_{job_id}"
		file_path = job_path / filename
		if not file_path.exists() or not file_path.resolve().is_relative_to(job_path.resolve()):
			raise HTTPException(status_code=404, detail={"detail": "File not found", "error_code": "NOT_FOUND"})

		return FileResponse(str(file_path), media_type="video/mp4", filename=filename)
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to download shorts clip for job %s", job_id)
		raise HTTPException(status_code=500, detail={"detail": "Download failed", "error_code": "DOWNLOAD_FAILED"}) from exc


@app.delete("/cleanup/{job_id}")
def cleanup(job_id: str) -> JSONResponse:
	logger.info("Received DELETE /cleanup/%s request", job_id)
	try:
		cleanup_job_folder(job_id)
		return JSONResponse(content={"message": "Cleaned up"})
	except Exception as exc:
		logger.exception("Failed to clean up job %s", job_id)
		raise HTTPException(status_code=500, detail={"detail": "Cleanup failed", "error_code": "CLEANUP_FAILED"}) from exc


@app.get("/thumbnail")
def thumbnail(video_path: str, ts: float = 2.0):
	try:
		thumb = generate_preview_thumbnail(video_path, video_path + ".thumb.jpg", timestamp=ts)
		if not thumb:
			raise HTTPException(status_code=500, detail={"detail": "Thumbnail failed", "error_code": "THUMBNAIL_FAILED"})
		return JSONResponse(content={"thumbnail_path": thumb})
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Thumbnail generation failed for %s: %s", video_path, exc)
		raise HTTPException(status_code=500, detail={"detail": "Thumbnail failed", "error_code": "THUMBNAIL_FAILED"}) from exc


@app.get("/health")
def health_check() -> JSONResponse:
	logger.info("Received GET /health request")
	try:
		temp_exists = pathlib.Path(config.TEMP_DIR).exists()
		music_dir = pathlib.Path(config.MUSIC_DIR)
		music_files_found = 0
		if music_dir.exists():
			music_files_found = len(list(music_dir.glob("*.mp3")))

		active_jobs = 0
		with job_store._jobs_lock:
			for j in job_store.jobs.values():
				if j.get("status") not in {"done", "queued", "error"}:
					active_jobs += 1

		payload = {
			"status": "ok",
			"service": "VideoClipper API",
			"version": "2.0.0",
			"groq_configured": bool(config.GROQ_API_KEY),
			"temp_dir_exists": temp_exists,
			"music_files_found": music_files_found,
			"active_jobs": active_jobs,
		}
		return JSONResponse(content=payload)
	except Exception as exc:
		logger.exception("Health check failed: %s", exc)
		raise HTTPException(status_code=500, detail={"detail": "Health check failed", "error_code": "HEALTH_FAILED"}) from exc


if __name__ == "__main__":
	uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
