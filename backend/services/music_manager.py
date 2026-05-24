"""
Music manager service for VideoClipper.
Selects royalty-free background music, applies intelligent volume ducking during speech.
Uses ffmpeg audio filters to seamlessly mix music into enhanced video clips.
"""

import logging
import os
import subprocess
from pathlib import Path
import random

from ..config import config


logger = logging.getLogger(__name__)


# Music directory and available tracks (configurable)
MUSIC_DIR = Path(config.MUSIC_DIR)

MUSIC_FILES = {
	"phonk": MUSIC_DIR / "phonk.mp3",
	"lofi": MUSIC_DIR / "lofi.mp3",
	"epic": MUSIC_DIR / "epic.mp3",
	"chill": MUSIC_DIR / "chill.mp3",
	"upbeat": MUSIC_DIR / "upbeat.mp3",
}

# Fallback order if chosen file doesn't exist
FALLBACK_ORDER = ["lofi", "chill", "upbeat", "epic", "phonk"]


def get_music_path(style: str) -> Path | None:
	"""
	Retrieves the path to a music file for the given style with fallback support.
	If the requested style is not available, tries fallback styles in order.

	Args:
		style: Music style name ("phonk", "lofi", "epic", "chill", "upbeat")

	Returns:
		Path to the music file, or None if no music files are available
	"""
	try:
		# Normalize the requested style
		normalized_style = style.lower().strip()

		# Check if the requested style exists and is a file
		if normalized_style in MUSIC_FILES:
			music_path = MUSIC_FILES[normalized_style]
			if music_path.exists():
				logger.debug(f"Using music style: {normalized_style}")
				return music_path

		# Try fallback styles if primary choice not found
		for fallback_style in FALLBACK_ORDER:
			fallback_path = MUSIC_FILES.get(fallback_style)
			if fallback_path and fallback_path.exists():
				logger.info(f"Primary style '{normalized_style}' not found, using fallback: {fallback_style}")
				return fallback_path

		# No music files found in the music directory
		logger.error(f"No music files found in {MUSIC_DIR}")
		return None

	except Exception as e:
		logger.error(f"Error getting music path: {e}")
		return None


def build_ducking_filter(speech_segments: list[dict], clip_start: float, clip_end: float) -> str:
	"""
	Builds an ffmpeg audio filter that automatically ducks (reduces) music volume during speech.
	Music plays at background level normally, becomes quieter when someone is speaking.

	Args:
		speech_segments: List of segment dicts with "start", "end", "text" keys (original timeline)
		clip_start: Clip start time in original video seconds
		clip_end: Clip end time in original video seconds

	Returns:
		ffmpeg audio filter string for volume ducking during speech
	"""
	try:
		# Filter segments to only those within this clip's time range
		speech_ranges = []

		for segment in speech_segments:
			try:
				seg_start = float(segment.get("start", 0))
				seg_end = float(segment.get("end", 0))

				# Check if segment overlaps with clip
				if seg_end <= clip_start or seg_start >= clip_end:
					continue

				# Convert to clip-relative time
				rel_start = max(0.0, seg_start - clip_start)
				rel_end = min(clip_end - clip_start, seg_end - clip_start)

				# Add 0.15s buffer on each side (prevents abrupt volume change at speech edges)
				buffered_start = max(0.0, rel_start - 0.15)
				buffered_end = rel_end + 0.15

				speech_ranges.append((buffered_start, buffered_end))

			except (ValueError, TypeError, KeyError):
				continue

		# Merge overlapping ranges to avoid complex filter expressions
		if speech_ranges:
			speech_ranges.sort()
			merged_ranges = []
			current_start, current_end = speech_ranges[0]

			for start, end in speech_ranges[1:]:
				if start <= current_end:
					# Overlap: extend current range
					current_end = max(current_end, end)
				else:
					# Gap: save current range and start new one
					merged_ranges.append((current_start, current_end))
					current_start, current_end = start, end

			merged_ranges.append((current_start, current_end))

			# Build enable expression for ffmpeg
			# Example: "between(t,0.50,3.20)+between(t,5.10,8.40)"
			speaking_conditions = [f"between(t,{start:.2f},{end:.2f})" for start, end in merged_ranges]
			speaking_expr = "+".join(speaking_conditions)

			logger.debug(f"Built speech ducking with {len(merged_ranges)} ranges")

			# Apply ducking: normal volume (0.22) reduces to (0.06) during speech
			# 0.22 = background volume (music present but not distracting from content)
			# 0.06 = ducked volume (barely audible during speech, keeps energy and presence)
			ducking_filter = f"volume=0.22,volume=enable='{speaking_expr}':volume=0.06:eval=frame"
			return ducking_filter

		else:
			# No speech detected in this clip — play music at full background volume
			logger.debug("No speech ranges detected in clip, using constant background volume")
			return "volume=0.22"

	except Exception as e:
		logger.warning(f"Error building ducking filter: {e}, using default background volume")
		return "volume=0.22"


def add_music_to_clip(
	video_path: str,
	output_path: str,
	music_style: str,
	speech_segments: list[dict],
	clip_start: float,
	clip_end: float,
) -> str:
	"""
	Mixes background music into an already-enhanced video clip with intelligent volume ducking.
	If music cannot be added, returns the original video unchanged.

	Args:
		video_path: Path to enhanced video (video has visual effects already, no audio music)
		output_path: Where to save final video with mixed music and ducking
		music_style: Music style ("phonk", "lofi", "epic", "chill", "upbeat")
		speech_segments: Transcript segments for ducking
		clip_start: Clip start in original video timeline
		clip_end: Clip end in original video timeline

	Returns:
		output_path on success or fallback to original video path if music fails
	"""
	try:
		# Get the music file path with fallback support
		music_path = get_music_path(music_style)

		if music_path is None:
			logger.warning(f"Music file for style '{music_style}' not found, returning video without music")
			# Copy original video to output as fallback
			import shutil
			shutil.copy2(video_path, output_path)
			return output_path

		# Build the volume ducking filter for speech
		ducking_filter = build_ducking_filter(speech_segments, clip_start, clip_end)

		# Build the ffmpeg filter_complex for audio mixing
		# This combines the original video audio with the background music and applies ducking
		filter_complex = (
			f"[1:a]{ducking_filter}[music_out];"
			"[0:a]volume=1.0[orig];"
			"[orig][music_out]amix=inputs=2:duration=first:dropout_transition=2[final_audio]"
		)

		# Build the ffmpeg command
		# -stream_loop -1: Loop the music file indefinitely so it fills the entire video duration
		# -map 0:v: Copy video stream from input 0 (enhanced video) — already encoded, just copy
		# -map [final_audio]: Use the mixed audio output from filter_complex
		# -c:v copy: Don't re-encode video, just copy the stream (saves time and quality)
		# -c:a aac: Encode the final mixed audio stream
		# -shortest: Stop when the shortest input ends (the video duration, not the looped music)
		command = [
			"ffmpeg",
			"-y",
			"-i",
			video_path,  # Input 0: enhanced video
			"-stream_loop",
			"-1",  # Loop music indefinitely so it never runs out
			"-i",
			str(music_path),  # Input 1: music file
			"-filter_complex",
			filter_complex,
			"-map",
			"0:v",  # Video from input 0 — already encoded
			"-map",
			"[final_audio]",  # Mixed audio from filter chain
			"-c:v",
			"copy",  # Copy video stream without re-encoding
			"-c:a",
			"aac",  # Encode mixed audio to AAC
			"-shortest",  # Stop when video ends (music is looped indefinitely)
			output_path,
		]

		logger.debug(f"Running ffmpeg music mixing: {' '.join(command)}")

		# Run the ffmpeg command
		result = subprocess.run(command, capture_output=True, text=True)

		# Check for errors
		if result.returncode != 0:
			error_msg = result.stderr.strip()
			logger.warning(f"ffmpeg music mixing failed: {error_msg}, returning video without music")
			# Copy original video to output as fallback
			import shutil
			shutil.copy2(video_path, output_path)
			return output_path

		# Log success
		logger.info(f"Music added successfully ({music_style}): {output_path}")
		return output_path

	except Exception as e:
		logger.warning(f"Unexpected error adding music: {e}, returning video without music")
		# Copy original video to output as fallback (music is optional, not critical)
		try:
			import shutil
			shutil.copy2(video_path, output_path)
		except Exception as copy_error:
			logger.error(f"Failed to copy fallback video: {copy_error}")
		return output_path


# Test module on import
if __name__ == "__main__":
	logger.info("music_manager.py loaded OK")
