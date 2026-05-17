"""
Streamlit frontend for VideoClipper.
This app uploads a video, starts processing, polls job status, and downloads clips.
"""

import os
import time

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


# Configure the Streamlit page before any other Streamlit calls are made.
st.set_page_config(page_title="VideoClipper", page_icon="🎬", layout="centered")


# Define the backend base URL and other app-wide constants.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
ALLOWED_VIDEO_TYPES = ["mp4", "mov", "avi", "mkv"]
POLL_INTERVAL_SECONDS = 3


# Initialize the session state variables used to track the current job.
def initialize_session_state() -> None:
	"""Creates the session state keys used by the app if they do not exist."""
	if "job_id" not in st.session_state:
		st.session_state.job_id = None
	if "processing" not in st.session_state:
		st.session_state.processing = False
	if "status_data" not in st.session_state:
		st.session_state.status_data = None


# Clear the current processing session so the user can start over.
def reset_session_state() -> None:
	"""Resets the app state back to the initial upload screen."""
	st.session_state.job_id = None
	st.session_state.processing = False
	st.session_state.status_data = None
	if "video_uploader" in st.session_state:
		del st.session_state["video_uploader"]


# Call the backend to start processing the uploaded video.
def start_processing(video_file, guidance_text: str) -> None:
	"""Uploads the selected video to the backend and stores the returned job ID."""
	try:
		# Validate inputs
		if not video_file:
			st.error("No video file selected")
			return
		
		if not guidance_text or not isinstance(guidance_text, str):
			guidance_text = ""
		
		# Truncate guidance if needed
		if len(guidance_text) > 500:
			guidance_text = guidance_text[:500]
			st.warning("Guidance text truncated to 500 characters")
		
		# Read the file bytes once so they can be sent as multipart form data.
		try:
			file_bytes = video_file.getvalue()
		except Exception as e:
			st.error(f"Failed to read video file: {e}")
			return
		
		files = {"video": (video_file.name, file_bytes, "video/mp4")}
		data = {"guidance": guidance_text}

		# Send the upload request to the FastAPI backend and wait for the job response.
		response = requests.post(
			f"{BACKEND_URL}/process",
			files=files,
			data=data,
			timeout=300,
		)

		# Surface any backend validation or processing errors to the user.
		if response.status_code >= 400:
			try:
				detail = response.json().get("detail", "Upload failed")
			except ValueError:
				detail = "Upload failed"
			st.error(detail)
			return

		# Store the returned job ID so the app can poll for progress.
		payload = response.json()
		st.session_state.job_id = payload.get("job_id")
		st.session_state.processing = True
		st.session_state.status_data = None
		st.rerun()

	except requests.exceptions.RequestException as exc:
		st.error(f"Upload failed: {exc}")
	except ValueError:
		st.error("Upload failed")


# Fetch the latest job status from the backend.
def fetch_job_status(job_id: str):
	"""Returns the current status payload for a job or None if the server is unavailable."""
	try:
		# Validate job_id
		if not job_id or not isinstance(job_id, str):
			st.error("Invalid job ID")
			return None
		
		# Ask the backend for the latest job status.
		response = requests.get(f"{BACKEND_URL}/status/{job_id}", timeout=10)

		# Treat non-success responses as a backend error and show the message when possible.
		if response.status_code >= 400:
			try:
				st.error(response.json().get("detail", "Failed to fetch status"))
			except ValueError:
				st.error("Failed to fetch status")
			return None

		# Return the parsed status dictionary for rendering.
		return response.json()

	except requests.exceptions.RequestException:
		st.warning("Waiting for server...")
		return None


# Download a generated clip from the backend as raw bytes.
def fetch_clip_bytes(job_id: str, filename: str):
	"""Downloads a clip file and returns its bytes, or None if the request fails."""
	try:
		# Validate inputs
		if not job_id or not filename:
			st.error("Invalid job ID or filename")
			return None
		
		# Sanitize filename to prevent path traversal
		filename = filename.strip()
		if "/" in filename or "\\" in filename or ".." in filename:
			st.error("Invalid filename")
			return None
		
		# Stream the file so the backend response can be used directly as download content.
		response = requests.get(
			f"{BACKEND_URL}/download/{job_id}/{filename}",
			stream=True,
			timeout=60,
		)

		# Reject non-success responses and surface the backend message if available.
		if response.status_code >= 400:
			try:
				st.error(response.json().get("detail", "Download failed"))
			except ValueError:
				st.error("Download failed")
			return None

		# Return the full file contents so Streamlit can use them in a download button.
		return response.content

	except requests.exceptions.RequestException as exc:
		st.error(f"Download failed: {exc}")
		return None


# Build a human-readable duration caption from a clip duration in seconds.
def format_duration(duration_seconds: float) -> str:
	"""Formats seconds as a compact minutes-and-seconds caption."""
	minutes = int(duration_seconds // 60)
	seconds = int(duration_seconds % 60)
	return f"Duration: {minutes}m {seconds}s"


# Run the app setup before rendering any UI content.
initialize_session_state()


# Render the header section for the app.
st.title("🎬 VideoClipper")
st.caption("Upload a video. Get the best clips. Powered by AI.")
st.divider()


# Render the upload section where the user chooses a source video.
uploaded_video = st.file_uploader(
	"Upload your video (max 500MB)",
	type=ALLOWED_VIDEO_TYPES,
	key="video_uploader",
)


# Render the mode selection controls only after a file has been uploaded.
guidance_text = ""
selected_mode = "auto"
if uploaded_video is not None:
	st.subheader("Select Mode")
	selected_mode = st.radio(
		"Choose how the AI should pick clips",
		[
			"🤖 Auto Mode — AI decides what's important",
			"🎯 Guided Mode — You tell the AI what to find",
		],
		horizontal=True,
		label_visibility="collapsed",
	)

	# Show the guidance prompt only when the user chooses guided mode.
	if selected_mode.startswith("🎯 Guided Mode"):
		guidance_text = st.text_input(
			"What should the AI look for?",
			placeholder="e.g. find the parts about machine learning, or highlight the key arguments",
		)


# Start processing only when a file is present and the user clicks the process button.
if uploaded_video is not None:
	if st.button("⚡ Process Video"):
		guidance_value = guidance_text if selected_mode.startswith("🎯 Guided Mode") else ""
		start_processing(uploaded_video, guidance_value)


# If a job is active, always refresh the latest status before deciding what to show.
if st.session_state.job_id:
	latest_status = fetch_job_status(st.session_state.job_id)
	if latest_status is not None:
		st.session_state.status_data = latest_status
		st.session_state.processing = latest_status.get("status") not in {"done", "error"}


# Render the progress section while the job is still running.
if st.session_state.job_id and st.session_state.status_data:
	current_status = st.session_state.status_data.get("status")
	if current_status not in {"done", "error"}:
		st.info(st.session_state.status_data.get("current_step", "Processing..."))
		st.progress(st.session_state.status_data.get("progress", 0) / 100)
		st.caption("This may take 1–3 minutes depending on video length")
		time.sleep(POLL_INTERVAL_SECONDS)
		st.rerun()


# Render the results section once the backend marks the job as complete.
if st.session_state.job_id and st.session_state.status_data:
	current_status = st.session_state.status_data.get("status")
	if current_status == "done":
		st.success("✅ Your clips are ready!")
		st.subheader("Download Your Clips")

		# Display each clip with its duration and an individual download button.
		for clip in st.session_state.status_data.get("clips", []):
			st.markdown(f"**{clip['label']}**")

			col1, col2 = st.columns([3, 1])
			with col1:
				st.caption(format_duration(clip["duration"]))
			with col2:
				clip_bytes = fetch_clip_bytes(st.session_state.job_id, clip["filename"])
				if clip_bytes is not None:
					st.download_button(
						label="⬇ Download",
						data=clip_bytes,
						file_name=clip["filename"],
						mime="video/mp4",
						key=f"download_{st.session_state.job_id}_{clip['filename']}",
					)

			st.divider()

		# Let the user clear the current job and upload another video.
		if st.button("Process another video"):
			reset_session_state()
			st.rerun()


# Render the error section if the backend reports a failed job.
if st.session_state.job_id and st.session_state.status_data:
	current_status = st.session_state.status_data.get("status")
	if current_status == "error":
		error_message = st.session_state.status_data.get("error", "Unknown error")
		st.error(f"❌ Something went wrong: {error_message}")

		# Let the user reset the app state after a failure.
		if st.button("Try Again"):
			reset_session_state()
			st.rerun()
