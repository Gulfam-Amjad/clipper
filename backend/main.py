"""
FastAPI backend entrypoint for VideoClipper.
This module wires together upload handling, the background pipeline, and job APIs.
"""

import logging
import pathlib
import uuid

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

from jobs.job_store import create_job, get_job, mark_done, mark_error, update_job
from models.schemas import ClipInfo, JobStatus, ProcessResponse
from services.analyzer import analyze_transcript
from services.audio_extractor import extract_audio
from services.clipper import cut_clips
from services.transcriber import transcribe_audio
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


# Run the clip-processing pipeline for a single job in the background thread.
def run_pipeline(job_id: str, video_path: str, guidance: str) -> None:
	"""
	Executes the end-to-end processing pipeline for a job.

	The function is intentionally synchronous because FastAPI BackgroundTasks
	executes regular callables in a worker thread.
	"""
	# Resolve the job folder path once so every pipeline step writes to the same location.
	job_folder = get_job_path(job_id)
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

	# Step A: extract audio from the uploaded video.
	try:
		update_job(job_id, "extracting_audio", "Extracting audio (Step 1 of 4)...", 10)
		audio_path = extract_audio(video_path, str(pathlib.Path(job_folder) / "audio.mp3"))
	except Exception as exc:
		logger.exception("Audio extraction failed for job %s", job_id)
		fail_job(exc)
		return

	# Step B: transcribe the extracted audio into timestamped segments.
	try:
		update_job(job_id, "transcribing", "Transcribing audio (Step 2 of 4)...", 35)
		segments = transcribe_audio(audio_path)
	except Exception as exc:
		logger.exception("Transcription failed for job %s", job_id)
		fail_job(exc)
		return

	# Step C: analyze the transcript and turn it into clip timestamp recommendations.
	try:
		update_job(job_id, "analyzing", "Analyzing content (Step 3 of 4)...", 60)
		clips = analyze_transcript(segments, guidance)
	except Exception as exc:
		logger.exception("Transcript analysis failed for job %s", job_id)
		fail_job(exc)
		return

	# Step D: cut the original video into individual clip files.
	try:
		update_job(job_id, "cutting", "Cutting clips (Step 4 of 4)...", 80)
		clip_results = cut_clips(video_path, clips, job_folder)
	except Exception as exc:
		logger.exception("Clip cutting failed for job %s", job_id)
		fail_job(exc)
		return

	# Mark the job as done and store the generated clip metadata.
	mark_done(job_id, clip_results)
	logger.info("Pipeline complete for job %s", job_id)


# Accept a video upload, validate it, persist it to the job folder, and queue background work.
@app.post("/process", response_model=ProcessResponse)
async def process_video(
	background_tasks: BackgroundTasks,
	video: UploadFile = File(...),
	guidance: str = Form(default="", max_length=500),
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
		background_tasks.add_task(run_pipeline, job_id, str(video_path), clean_guidance)

		# Return the job identifier so the client can poll status.
		return ProcessResponse(job_id=job_id, message="Processing started")

	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to start processing job")
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

		return JobStatus(**job)

	except HTTPException:
		raise
	except Exception as exc:
		logger.exception("Failed to fetch status for job %s", job_id)
		raise HTTPException(status_code=500, detail=str(exc)) from exc


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
