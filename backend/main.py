"""
FastAPI backend entrypoint for VideoClipper.
This module wires together upload handling, the background pipeline, and job APIs.
"""

import logging
import pathlib
import uuid
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

from jobs import job_store
from jobs.job_store import create_job, get_job, mark_done, mark_error, update_job
from models.schemas import ClipInfo, JobStatus, ProcessResponse
from services.analyzer import analyze_transcript, score_clips
from services.audio_extractor import extract_audio
from services.clipper import cut_all_shorts, cut_clips
from services.transcriber import transcribe_audio
from services.youtube_downloader import (
	download_youtube_video,
	get_video_info,
	validate_youtube_url,
)
from utils.file_manager import cleanup_job_folder, create_job_folder, get_job_path
from utils.validators import validate_video_file


# Configure application-wide logging so every request and pipeline step is visible.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Create the FastAPI application and enable permissive CORS for the web client.
app = FastAPI(title="VideoClipper API", version="1.0.0")
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


# Ensure the shared temp directory exists before any job is created.
@app.on_event("startup")
def ensure_temp_directory() -> None:
	"""Create the temp directory used for per-job files if it does not exist."""
	pathlib.Path("temp").mkdir(parents=True, exist_ok=True)
	logger.info("Temp directory initialized")


@app.on_event("startup")
async def startup_event():
	"""Start application-level services such as the cleanup scheduler."""
	try:
		os.makedirs("temp", exist_ok=True)
		from services.cleanup_scheduler import start_cleanup_scheduler, stop_cleanup_scheduler

		app.state.scheduler = start_cleanup_scheduler()
		logging.info("Application started")
	except Exception:
		logger.exception("Failed to start application services on startup")


@app.on_event("shutdown")
async def shutdown_event():
	"""Stop background services cleanly on application shutdown."""
	try:
		if hasattr(app.state, "scheduler"):
			from services.cleanup_scheduler import stop_cleanup_scheduler

			stop_cleanup_scheduler(app.state.scheduler)
	except Exception:
		logger.exception("Error stopping application services on shutdown")


def _set_job_metadata(job_id: str, **fields: object) -> None:
	"""Persist extra metadata fields directly in the in-memory job store."""
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
	"""Executes the shared processing pipeline for an already available local video file."""
	logger.info("Pipeline started for job %s", job_id)

	# Centralize failure handling so a job is marked failed and temporary files are removed.
	def fail_job(error: Exception) -> None:
		try:
			mark_error(job_id, str(error))
		finally:
			try:
				cleanup_job_folder(job_id)
			except Exception:
				logger.exception("Cleanup failed for job %s after an error", job_id)

	# If this flow started from /process-url, the download step already consumed Step 0.
	job_snapshot = get_job(job_id) or {}
	started_from_youtube = job_snapshot.get("status") == "downloading"
	step_offset = 1 if started_from_youtube else 0
	step_total = (6 if generate_shorts else 5) if started_from_youtube else (5 if generate_shorts else 4)

	# Step A: extract audio from the uploaded video.
	try:
		update_job(
			job_id,
			"extracting_audio",
			f"Extracting audio (Step {1 + step_offset} of {step_total})...",
			20,
		)
		audio_path = extract_audio(video_path, str(pathlib.Path(job_folder) / "audio.mp3"))
	except Exception as exc:
		logger.exception("Audio extraction failed for job %s", job_id)
		fail_job(exc)
		return

	# Step B: transcribe the extracted audio into timestamped segments.
	try:
		update_job(
			job_id,
			"transcribing",
			f"Transcribing audio (Step {2 + step_offset} of {step_total})...",
			45,
		)
		segments = transcribe_audio(audio_path, language=language)
	except Exception as exc:
		logger.exception("Transcription failed for job %s", job_id)
		fail_job(exc)
		return

	# Step C: analyze the transcript and turn it into clip timestamp recommendations.
	try:
		update_job(
			job_id,
			"analyzing",
			f"Analyzing content (Step {3 + step_offset} of {step_total})...",
			65,
		)
		clips, music_style = analyze_transcript(segments, guidance or None)
		clips = score_clips(clips, segments)
		_set_job_metadata(job_id, music_style=music_style)
	except Exception as exc:
		logger.exception("Transcript analysis failed for job %s", job_id)
		fail_job(exc)
		return

	# Step D: cut the original video into individual clip files.
	try:
		update_job(
			job_id,
			"cutting",
			f"Cutting clips (Step {4 + step_offset} of {step_total})...",
			85,
		)
		clip_results = cut_clips(
			video_path,
			clips,
			job_folder,
			all_segments=segments,
			music_style=music_style,
			is_shorts=False,
		)
	except Exception as exc:
		logger.exception("Clip cutting failed for job %s", job_id)
		fail_job(exc)
		return

	# Step E: generate YouTube Shorts versions (optional).
	shorts_clips = []
	if generate_shorts:
		update_job(
			job_id,
			"creating_shorts",
			f"Creating Shorts versions (Step {5 + step_offset} of {step_total})...",
			92,
		)
		try:
			shorts_clips = cut_all_shorts(
				video_path,
				clips,
				job_folder,
				all_segments=segments,
				music_style=music_style,
			)
			logging.info(f"Job {job_id}: {len(shorts_clips)} shorts clips created")
		except Exception as e:
			# Shorts failure must NOT fail the whole job
			# Normal clips are already done - just log and continue
			logging.warning(f"Job {job_id}: Shorts generation failed: {e}")
			shorts_clips = []

	# Mark the job as done and store the generated clip metadata.
	mark_done(job_id, clip_results)

	# Step F — Generate titles and metadata
	try:
		from services.title_generator import generate_all_metadata
		clip_results = generate_all_metadata(clip_results, segments)
		job = get_job(job_id)
		if job:
			job["clips"] = clip_results
		logging.info(f"Job {job_id}: Metadata generation complete")
	except Exception as e:
		logging.warning(f"Job {job_id}: Metadata generation failed (non-critical): {e}")

	# Step G — Viral scoring
	try:
		from services.viral_scorer import score_all_clips
		clip_results = score_all_clips(clip_results, segments, use_llm=True)
		job = get_job(job_id)
		if job:
			job["clips"] = clip_results
		logging.info(f"Job {job_id}: Viral scoring complete")
	except Exception as e:
		logging.warning(f"Job {job_id}: Viral scoring failed (non-critical): {e}")

	# Step H — Chapter detection
	try:
		from services.chapter_detector import detect_chapters, format_chapters_for_youtube
		video_duration = segments[-1]["end"] if segments else 0
		chapters = detect_chapters(segments, video_duration)
		youtube_chapters = format_chapters_for_youtube(chapters)
		job = get_job(job_id)
		if job:
			job["chapters"] = chapters
			job["youtube_chapters"] = youtube_chapters
		logging.info(f"Job {job_id}: Chapter detection complete — {len(chapters)} chapters")
	except Exception as e:
		logging.warning(f"Job {job_id}: Chapter detection failed (non-critical): {e}")

	# Add shorts and music style to the job entry.
	_set_job_metadata(job_id, shorts_clips=shorts_clips, music_style=music_style)

	logger.info("Pipeline complete for job %s", job_id)


# Run the clip-processing pipeline for an uploaded file in the background thread.
def run_pipeline(job_id: str, video_path: str, guidance: str, generate_shorts: bool = False, language: str = "en") -> None:
	"""
	Wrapper for uploaded-file jobs that delegates into the shared video pipeline.

	The function is intentionally synchronous because FastAPI BackgroundTasks
	executes regular callables in a worker thread.
	
	Args:
		job_id: Unique job identifier
		video_path: Path to the uploaded video file
		guidance: Optional user guidance text for clip analysis
		generate_shorts: If True, also generate YouTube Shorts (9:16) versions of clips
	"""
	job_folder = get_job_path(job_id)
	run_pipeline_from_video(job_id, video_path, job_folder, guidance, generate_shorts, language=language)


def run_youtube_pipeline(
	job_id: str,
	youtube_url: str,
	job_folder: str,
	guidance: str,
	generate_shorts: bool,
) -> None:
	"""Background task that downloads a YouTube video, then runs the shared pipeline."""
	total_steps = 6 if generate_shorts else 5
	try:
		update_job(
			job_id,
			"downloading",
			f"Downloading YouTube video (Step 0 of {total_steps})...",
			5,
		)
		video_path = download_youtube_video(youtube_url, job_folder)
		logging.info(f"Job {job_id}: Downloaded to {video_path}")
	except Exception as e:
		mark_error(job_id, f"Download failed: {str(e)}")
		return

	# Steps 1-5: shared pipeline from local video path.
	run_pipeline_from_video(job_id, video_path, job_folder, guidance, generate_shorts)


# Accept a video upload, validate it, persist it to the job folder, and queue background work.
@app.post("/process", response_model=ProcessResponse)
async def process_video(
	background_tasks: BackgroundTasks,
	video: UploadFile = File(...),
	guidance: str = Form(default="", max_length=500),
	shorts_mode: str = Form(default="false"),
	language: str = Form(default="en"),
) -> ProcessResponse:
	"""Receives an uploaded video and starts the processing pipeline."""
	logger.info("Received POST /process request for filename=%s", video.filename)

	try:
		# Read the uploaded file into memory so its size can be validated first.
		file_content = await video.read()
		filename = video.filename or ""

		# Validate the uploaded file before creating any job state or writing to disk.
		is_valid, error_message = validate_video_file(filename, len(file_content))
		if not is_valid:
			raise HTTPException(status_code=400, detail=error_message)

		# Sanitize guidance text to prevent injection attacks
		clean_guidance = (guidance or "").strip()
		if len(clean_guidance) > 500:
			clean_guidance = clean_guidance[:500]

		# Convert shorts_mode string to boolean
		generate_shorts = shorts_mode.lower() == "true"

		# Create a new job and its working directory for the uploaded file.
		job_id = str(uuid.uuid4())
		create_job(job_id)
		job_folder = create_job_folder(job_id)

		# Determine the original file extension so the saved video keeps the right type.
		file_extension = pathlib.Path(filename).suffix or ".mp4"
		video_path = pathlib.Path(job_folder) / f"video{file_extension}"

		# Write the uploaded bytes to the job folder for the background pipeline.
		with open(video_path, "wb") as output_file:
			output_file.write(file_content)

		# Queue the background pipeline after the upload has been persisted.
		background_tasks.add_task(run_pipeline, job_id, str(video_path), clean_guidance, generate_shorts, language)

		# Return the job identifier so the client can poll status.
		return ProcessResponse(job_id=job_id, message="Processing started")

	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to start processing job")
		raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/process-url", response_model=ProcessResponse)
async def process_url(
	background_tasks: BackgroundTasks,
	youtube_url: str = Form(...),
	guidance: str = Form(default=""),
	shorts_mode: str = Form(default="false"),
) -> ProcessResponse:
	"""Validates a YouTube URL, creates a job, and starts background download + processing."""
	logger.info("Received POST /process-url request")

	try:
		valid, error_msg = validate_youtube_url(youtube_url)
		if not valid:
			raise HTTPException(400, f"Invalid YouTube URL: {error_msg}")

		clean_guidance = (guidance or "").strip()
		if len(clean_guidance) > 500:
			clean_guidance = clean_guidance[:500]

		job_id = str(uuid.uuid4())
		create_job(job_id)
		job_folder = create_job_folder(job_id)

		generate_shorts = shorts_mode.lower() == "true"

		background_tasks.add_task(
			run_youtube_pipeline, job_id, youtube_url, job_folder, clean_guidance, generate_shorts
		)

		return ProcessResponse(job_id=job_id, message="YouTube video download started")
	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to start YouTube processing job")
		raise HTTPException(status_code=500, detail=str(exc)) from exc


# Return the current state of a job so the client can poll progress.
@app.get("/status/{job_id}", response_model=JobStatus)
def get_status(job_id: str) -> JobStatus:
	"""Returns the current processing status for the requested job."""
	logger.info("Received GET /status/%s request", job_id)

	try:
		# Look up the job and convert it into the response schema.
		job = get_job(job_id)
		if job is None:
			raise HTTPException(status_code=404, detail="Job not found")

		# Include shorts_clips in response if they exist
		job_data = dict(job)
		if "shorts_clips" not in job_data:
			job_data["shorts_clips"] = []
		job_data["music_style"] = job_data.get("music_style", "lofi")

		# Include chapters and YouTube-formatted chapters if present
		if "chapters" not in job_data:
			job_data["chapters"] = []
		if "youtube_chapters" not in job_data:
			job_data["youtube_chapters"] = ""

		return JobStatus(**job_data)

	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to fetch status for job %s", job_id)
		raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/video-info")
async def video_info(url: str):
	"""Returns metadata for a YouTube URL without downloading the video."""
	valid, err = validate_youtube_url(url)
	if not valid:
		raise HTTPException(400, err)
	try:
		info = get_video_info(url)
		return info
	except Exception as e:
		raise HTTPException(500, str(e))


	@app.get("/languages")
	def get_languages():
		"""Return supported transcription languages."""
		try:
			from services.transcriber import get_supported_languages

			return get_supported_languages()
		except Exception:
			logger.exception("Failed to return supported languages")
			raise HTTPException(status_code=500, detail="Failed to load supported languages")


# Serve a finished clip file from the job's temp directory.
@app.get("/download/{job_id}/{filename}")
def download_clip(job_id: str, filename: str) -> FileResponse:
	"""Downloads a generated clip if the job has finished successfully."""
	logger.info("Received GET /download/%s/%s request", job_id, filename)

	try:
		# Ensure the job exists and has completed before serving any files.
		job = get_job(job_id)
		if job is None or job.get("status") != "done":
			raise HTTPException(status_code=404, detail="Clip not available")

		# Only allow filenames that were actually produced for this job.
		job_clips = job.get("clips") or []
		allowed_filenames = {
			clip.get("filename")
			for clip in job_clips
			if isinstance(clip, dict) and clip.get("filename")
		}
		if filename not in allowed_filenames:
			raise HTTPException(status_code=404, detail="File not found")

		# Build the expected file path inside the job folder.
		job_path = pathlib.Path("temp") / f"job_{job_id}"
		file_path = job_path / filename
		if not file_path.resolve().is_relative_to(job_path.resolve()):
			raise HTTPException(status_code=400, detail="Invalid filename")
		if not file_path.exists():
			raise HTTPException(status_code=404, detail="File not found")

		# Return the file as an MP4 download.
		return FileResponse(str(file_path), media_type="video/mp4", filename=filename)

	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to download clip for job %s", job_id)
		raise HTTPException(status_code=500, detail=str(exc)) from exc


# Serve a finished Shorts file from the job's temp directory.
@app.get("/download-shorts/{job_id}/{filename}")
def download_shorts(job_id: str, filename: str) -> FileResponse:
	"""Downloads a generated Shorts clip if the job has finished successfully."""
	logger.info("Received GET /download-shorts/%s/%s request", job_id, filename)

	try:
		# Ensure the job exists and has completed before serving any files.
		job = get_job(job_id)
		if job is None or job.get("status") != "done":
			raise HTTPException(status_code=404, detail="Shorts clip not available")

		# Only allow filenames that start with "shorts_" (security check).
		if not filename.startswith("shorts_"):
			raise HTTPException(status_code=400, detail="Invalid filename")

		# Only allow .mp4 filenames.
		if not filename.endswith(".mp4"):
			raise HTTPException(status_code=400, detail="Invalid file format")

		# Only allow filenames that were actually produced for this job.
		job_shorts = job.get("shorts_clips") or []
		allowed_filenames = {
			short.get("filename")
			for short in job_shorts
			if isinstance(short, dict) and short.get("filename")
		}
		if filename not in allowed_filenames:
			raise HTTPException(status_code=404, detail="File not found")

		# Build the expected file path inside the job folder.
		job_path = pathlib.Path("temp") / f"job_{job_id}"
		file_path = job_path / filename
		if not file_path.resolve().is_relative_to(job_path.resolve()):
			raise HTTPException(status_code=400, detail="Invalid filename")
		if not file_path.exists():
			raise HTTPException(status_code=404, detail="File not found")

		# Return the file as an MP4 download.
		return FileResponse(str(file_path), media_type="video/mp4", filename=filename)

	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to download shorts clip for job %s", job_id)
		raise HTTPException(status_code=500, detail=str(exc)) from exc


# Remove the job directory when the client is done with the generated clips.
@app.delete("/cleanup/{job_id}")
def cleanup(job_id: str) -> JSONResponse:
	"""Deletes the temporary job folder and all generated artifacts."""
	logger.info("Received DELETE /cleanup/%s request", job_id)

	try:
		# Delegate folder removal to the shared file manager utility.
		cleanup_job_folder(job_id)
		return JSONResponse(content={"message": "Cleaned up"})

	except Exception as exc:
		logger.exception("Failed to clean up job %s", job_id)
		raise HTTPException(status_code=500, detail=str(exc)) from exc


# Provide a simple health endpoint for deployment checks.
@app.get("/health")
def health_check() -> JSONResponse:
	"""Returns a basic service health response."""
	logger.info("Received GET /health request")

	try:
		# Return a compact JSON payload that confirms the API is alive.
		return JSONResponse(content={"status": "ok", "service": "VideoClipper API"})

	except Exception as exc:
		logger.exception("Health check failed")
		raise HTTPException(status_code=500, detail=str(exc)) from exc


# Allow running the API directly with uvicorn during local development.
if __name__ == "__main__":
	uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
