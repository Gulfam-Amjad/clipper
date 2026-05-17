"""
Video enhancement service for VideoClipper.
Applies cinematic visual effects, watermarks, subtitles, and smart face-crop to video clips.
Uses ffmpeg for all video processing and mediapipe for intelligent face detection.
"""

import logging
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def detect_face_center_x(video_path: str, clip_start: float, clip_end: float) -> float:
	"""
	Analyzes a video clip to find the average horizontal position of detected faces.
	Used for intelligent cropping in Shorts mode (crops around subject, not just center).

	Args:
		video_path: Path to the video file
		clip_start: Start time in seconds
		clip_end: End time in seconds

	Returns:
		Float between 0.0 (left) and 1.0 (right) representing average face X position.
		Returns 0.5 (center) if no faces detected or on any error.
	"""
	try:
		# Import mediapipe here to handle graceful fallback if unavailable
		try:
			from mediapipe.tasks import python as mp_python
			from mediapipe.tasks.python import vision
		except ImportError:
			logger.debug("mediapipe not available, using default face center")
			return 0.5

		# Open video file and get frame rate
		cap = cv2.VideoCapture(video_path)
		if not cap.isOpened():
			logger.warning(f"Failed to open video for face detection: {video_path}")
			return 0.5

		fps = cap.get(cv2.CAP_PROP_FPS)
		if fps <= 0:
			logger.warning(f"Invalid FPS for video: {video_path}")
			cap.release()
			return 0.5

		# Calculate total frames in the clip
		total_frames_in_clip = int((clip_end - clip_start) * fps)
		if total_frames_in_clip <= 0:
			logger.warning(f"Invalid clip duration: {clip_start} to {clip_end}")
			cap.release()
			return 0.5

		# Sample 10 evenly spaced frames across the clip
		sample_count = 10
		face_x_positions = []

		# Create face detector with minimal configuration
		try:
			base_options = mp_python.BaseOptions(model_asset_path=None)
			options = vision.FaceDetectorOptions(base_options=base_options, min_detection_confidence=0.5)
			detector = vision.FaceDetector.create_from_options(options)
		except Exception as e:
			logger.warning(f"Could not initialize mediapipe face detector: {e}")
			cap.release()
			return 0.5

		try:
			for i in range(sample_count):
				# Calculate time position for this sample
				sample_fraction = i / sample_count
				sample_time_ms = (clip_start + sample_fraction * (clip_end - clip_start)) * 1000

				# Seek to the sample time
				cap.set(cv2.CAP_PROP_POS_MSEC, sample_time_ms)
				ret, frame = cap.read()

				if not ret:
					continue

				# Convert BGR to RGB
				frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
				
				# Create mediapipe image
				mp_image = vision.Image(image_format=vision.ImageFormat.SRGB, data=frame_rgb)

				# Detect faces in this frame
				detection_result = detector.detect(mp_image)

				# Record face X positions if detected
				if detection_result.detections:
					for detection in detection_result.detections:
						# Face bounding box is normalized (0.0 to 1.0)
						bbox = detection.bounding_box
						face_center_x = bbox.origin_x + bbox.width / 2
						face_x_positions.append(face_center_x)

		finally:
			try:
				detector.close()
			except:
				pass
			cap.release()

		# Return average face position or default to center
		if face_x_positions:
			avg_face_x = np.mean(face_x_positions)
			logger.debug(f"Detected {len(face_x_positions)} faces, average X position: {avg_face_x:.2f}")
			return float(avg_face_x)
		else:
			logger.debug(f"No faces detected in clip {clip_start}-{clip_end}, defaulting to center")
			return 0.5

	except Exception as e:
		logger.warning(f"Error detecting faces: {e}, defaulting to center")
		return 0.5


def build_video_filter_chain(
	clip_duration: float,
	watermark_text: str,
	subtitle_path: str | None,
	is_shorts: bool,
	face_center_x: float,
	video_width: int,
	video_height: int,
) -> str:
	"""
	Builds the complete ffmpeg video filter chain with all cinematic enhancements.
	Filters are applied in a specific order that matters for ffmpeg processing.

	Args:
		clip_duration: Clip length in seconds (for fade-out timing)
		watermark_text: Text to display as watermark (e.g. "Gulfam")
		subtitle_path: Path to .ass subtitle file (or None to skip)
		is_shorts: Whether to apply portrait crop for Shorts format
		face_center_x: Normalized horizontal face position (0.0-1.0) for smart crop
		video_width: Original video width in pixels
		video_height: Original video height in pixels

	Returns:
		Single ffmpeg filter chain string ready to pass to -vf argument
	"""
	filters = []

	try:
		# STEP 1 — Portrait crop for Shorts (only if requested)
		if is_shorts:
			crop_width = int(video_height * 9 / 16)  # 9:16 aspect ratio
			# Position crop based on detected face, with bounds checking
			crop_x = int(face_center_x * video_width - crop_width / 2)
			crop_x = max(0, min(crop_x, video_width - crop_width))
			crop_filter = f"crop={crop_width}:{video_height}:{crop_x}:0,scale=1080:1920"
			filters.append(crop_filter)
			logger.debug(f"Shorts crop: width={crop_width}, x_offset={crop_x}, face_center_x={face_center_x:.2f}")

		# STEP 2 — Color grading for cinematic look
		# brightness=0.04: subtle lift (avoids flat look)
		# contrast=1.12: punchy contrast (cinematic feel)
		# saturation=1.25: vivid colors (more engaging on mobile)
		# gamma=0.97: slightly cooler midtones
		color_grade = "eq=brightness=0.04:contrast=1.12:saturation=1.25:gamma=0.97"
		filters.append(color_grade)

		# STEP 3 — Luma sharpening for crisp appearance
		# 5x5 matrix with 0.6 strength — makes video look sharp without artifacts
		sharpen = "unsharp=5:5:0.6:5:5:0.0"
		filters.append(sharpen)

		# STEP 4 — Vignette effect (darkens corners, draws eye to center)
		# PI/4.5 creates subtle corner darkening for cinematic feel
		vignette = "vignette=PI/4.5"
		filters.append(vignette)

		# STEP 5 — Hue shift for copyright differentiation
		# 8-degree hue rotation subtly transforms colors — differentiates clip from source
		# for content originality and social media compliance
		hue_shift = "hue=h=8:s=1"
		filters.append(hue_shift)

		# STEP 6 — White flash fade-in at clip start (cinematic entry effect)
		# 0.25 second fade from white creates dramatic clip opening
		fade_in = "fade=t=in:st=0:d=0.25:color=white"
		filters.append(fade_in)

		# STEP 7 — Smooth fade-out at clip end
		# 0.4 second fade positioned 0.4s before clip ends
		fade_out = f"fade=t=out:st={max(0, clip_duration - 0.4)}:d=0.4"
		filters.append(fade_out)

		# STEP 8 — Burn subtitles if provided
		# ASS format supports rich styling (colors, fonts, positioning)
		if subtitle_path and os.path.exists(subtitle_path):
			# Convert backslashes to forward slashes for ffmpeg compatibility
			safe_subtitle_path = subtitle_path.replace("\\", "/")
			subtitle_filter = f"ass={safe_subtitle_path}"
			filters.append(subtitle_filter)
			logger.debug(f"Added subtitle filter: {subtitle_filter}")

		# STEP 9 — Watermark text (bottom-right with drop shadow)
		# Semi-transparent white text with black shadow and subtle box background
		# fontcolor=white@0.75: 75% opaque white text
		# shadowcolor=black@0.55: 55% opaque black drop shadow
		# boxcolor=black@0.3: 30% opaque black background box
		watermark_filter = (
			f"drawtext=text='{watermark_text}':"
			"fontcolor=white@0.75:"
			"fontsize=22:"
			"x=w-tw-18:"
			"y=h-th-18:"
			"shadowcolor=black@0.55:"
			"shadowx=2:"
			"shadowy=2:"
			"box=1:"
			"boxcolor=black@0.3:"
			"boxborderw=6"
		)
		filters.append(watermark_filter)

		# Combine all filters with comma separator
		filter_chain = ",".join(filters)
		logger.debug(f"Built filter chain ({len(filters)} filters): {filter_chain[:200]}...")
		return filter_chain

	except Exception as e:
		logger.error(f"Error building filter chain: {e}")
		raise


def apply_enhancements(
	input_path: str,
	output_path: str,
	clip_duration: float,
	watermark_text: str,
	subtitle_path: str | None,
	is_shorts: bool,
	face_center_x: float,
	video_width: int,
	video_height: int,
) -> str:
	"""
	Applies all visual enhancements to a video clip using ffmpeg.
	Handles color grading, watermark, subtitles, and smart face cropping.

	Args:
		input_path: Path to source clip
		output_path: Path where enhanced clip will be saved
		clip_duration: Clip length in seconds
		watermark_text: Watermark text to display
		subtitle_path: Path to .ass subtitle file (or None)
		is_shorts: Whether to apply portrait crop
		face_center_x: Normalized face X position (0.0-1.0)
		video_width: Original video width
		video_height: Original video height

	Returns:
		output_path on success

	Raises:
		RuntimeError: If ffmpeg processing fails
	"""
	try:
		# Build the complete filter chain
		filter_chain = build_video_filter_chain(
			clip_duration, watermark_text, subtitle_path, is_shorts, face_center_x, video_width, video_height
		)

		# Log the filter chain for debugging
		logger.info(f"Applying enhancements to {input_path}")
		logger.debug(f"Filter chain: {filter_chain}")

		# Build ffmpeg command
		# -c:v libx264: h.264 codec for compatibility
		# -preset fast: balance between encoding speed and quality (better than ultrafast)
		# -crf 20: quality (18=best, 28=worst; 20 is high quality)
		# -threads 4: use 4 CPU threads
		# -c:a copy: copy audio without re-encoding (music will be added later separately)
		command = [
			"ffmpeg",
			"-y",
			"-i",
			input_path,
			"-vf",
			filter_chain,
			"-c:v",
			"libx264",
			"-preset",
			"fast",
			"-crf",
			"20",
			"-threads",
			"4",
			"-c:a",
			"copy",
			output_path,
		]

		# Run ffmpeg
		logger.debug(f"Running ffmpeg: {' '.join(command)}")
		result = subprocess.run(command, capture_output=True, text=True)

		# Check for errors
		if result.returncode != 0:
			error_msg = result.stderr.strip()
			logger.error(f"ffmpeg enhancement failed: {error_msg}")
			raise RuntimeError(f"Video enhancement failed: {error_msg}")

		# Log success with file size
		output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
		logger.info(f"Successfully enhanced video: {output_path} ({output_size_mb:.1f} MB)")
		return output_path

	except FileNotFoundError:
		logger.error("ffmpeg not found in system PATH")
		raise RuntimeError("ffmpeg is not installed or not in PATH")
	except Exception as e:
		logger.exception(f"Unexpected error during video enhancement: {e}")
		raise RuntimeError(f"Video enhancement error: {e}")


def get_video_dimensions(video_path: str) -> tuple[int, int]:
	"""
	Retrieves the width and height of a video file using ffprobe.

	Args:
		video_path: Path to the video file

	Returns:
		Tuple of (width, height) in pixels
		Returns (1920, 1080) as safe default if ffprobe fails
	"""
	try:
		# Use ffprobe to get video dimensions
		command = [
			"ffprobe",
			"-v",
			"error",
			"-select_streams",
			"v:0",
			"-show_entries",
			"stream=width,height",
			"-of",
			"csv=s=x:p=0",
			video_path,
		]

		result = subprocess.run(command, capture_output=True, text=True)

		# Parse output: "width x height"
		output = result.stdout.strip()
		if "x" in output:
			width_str, height_str = output.split("x")
			width = int(width_str)
			height = int(height_str)
			logger.debug(f"Video dimensions: {width}x{height}")
			return (width, height)
		else:
			logger.warning(f"Could not parse ffprobe output: {output}")
			return (1920, 1080)

	except Exception as e:
		logger.warning(f"Error getting video dimensions: {e}, using default (1920x1080)")
		return (1920, 1080)


# Test module on import
if __name__ == "__main__":
	print("video_enhancer.py loaded OK")
