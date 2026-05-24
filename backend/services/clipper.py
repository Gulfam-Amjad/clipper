"""
Video clip cutting service for VideoClipper.
This module turns clip timestamps into individual video files using ffmpeg.
"""

import concurrent.futures
import logging
import subprocess
from pathlib import Path

from .music_manager import add_music_to_clip
from .subtitle_generator import segments_to_ass
from .video_enhancer import (
	apply_enhancements,
	detect_face_center_x,
	get_video_dimensions,
)
from ..config import config
from ..utils.validators import sanitize_label


logger = logging.getLogger(__name__)


def generate_thumbnail(video_path: str, timestamp: float, output_path: str):
	"""
	Extracts a single video frame at the given timestamp and saves it as a JPEG thumbnail.

	Args:
		video_path: Path to the original video file
		timestamp: Point in seconds to grab the frame
		output_path: Where to save the .jpg file

	Returns:
		output_path string on success, None if thumbnail generation failed

	Note:
		Thumbnail generation is optional and non-critical. Errors are logged
		but do not interrupt the clip cutting process.
	"""
	try:
		# Validate input video file exists
		video_file = Path(video_path)
		if not video_file.exists():
			logger.warning(f"Video file not found for thumbnail: {video_path}")
			return None

		# Build the ffmpeg command for thumbnail extraction
		# -ss {timestamp} = seek to this point BEFORE opening file (fast seek)
		# -vframes 1      = extract exactly 1 frame
		# -q:v 2          = JPEG quality (scale 1-31, lower = better, 2 = high quality)
		command = [
			"ffmpeg",
			"-y",
			"-ss",
			str(timestamp),
			"-i",
			video_path,
			"-vframes",
			"1",
			"-q:v",
			"2",
			str(output_path),
		]

		# Log the command before execution
		logger.debug(f"Generating thumbnail: {' '.join(command)}")

		# Run ffmpeg to extract the frame
		result = subprocess.run(command, capture_output=True, text=True)

		# Check if thumbnail extraction succeeded
		if result.returncode != 0:
			logger.warning(
				f"ffmpeg thumbnail extraction failed for {output_path}: {result.stderr.strip()}"
			)
			return None

		# Verify the thumbnail was created
		output_file = Path(output_path)
		if not output_file.exists():
			logger.warning(f"Thumbnail file not created: {output_path}")
			return None

		logger.debug(f"Thumbnail generated successfully: {output_path}")
		return str(output_path)

	except FileNotFoundError:
		logger.warning("ffmpeg not found - cannot generate thumbnail")
		return None
	except Exception as e:
		logger.warning(f"Unexpected error during thumbnail generation: {str(e)}")
		return None


def cut_clips(
	video_path: str,
	clips: list[dict],
	output_folder: str,
	all_segments: list[dict] | None = None,
	music_style: str = "lofi",
	is_shorts: bool = False,
) -> list[dict]:
	"""
	Cuts a source video into individual clip files using ffmpeg in parallel.

	Args:
		video_path: Path to the original uploaded video.
		clips: List of clip dictionaries with start, end, and label values.
		output_folder: Folder where the generated clip files should be saved.

	Returns:
		A list of dictionaries describing each successfully created clip.
		Each dict includes: filename, label, start, end, duration, thumbnail_path

	Raises:
		RuntimeError: If ffmpeg is not available or if every clip fails.
	"""
	if all_segments is None:
		all_segments = []
	filename_prefix = "shorts" if is_shorts else "clip"

	# Prepare the output directory
	output_directory = Path(output_folder)
	output_directory.mkdir(parents=True, exist_ok=True)

	def cut_single_clip(clip: dict, index: int):
		"""
		Cuts a single clip from the source video and optionally generates a thumbnail.
		This function is executed in parallel by ThreadPoolExecutor.

		Args:
			clip: Dictionary with start, end, and label
			index: Clip index (1-based) for logging and filename

		Returns:
			Dictionary with clip metadata (filename, label, start, end, duration, thumbnail_path),
			or None if this clip failed to cut.
		"""
		try:
			# Read the clip fields and derive the output filename from the label.
			start = float(clip["start"])
			end = float(clip["end"])
			duration = end - start
			label = str(clip.get("label", "clip"))
			sanitized_label = sanitize_label(label)
			raw_filename = f"{filename_prefix}_{index}_{sanitized_label}_raw.mp4"
			raw_clip_path = output_directory / raw_filename

			# Stage 1 - Raw cut from source video
			logger.info("Clip %s - Stage 1: Raw cut", index)
			try:
				# Build the ffmpeg command that re-encodes video and audio for clean cuts.
				# -y = overwrite if exists
				# -ss {start} = seek to start time in seconds
				# -to {end} = stop at end time in seconds
				# -c:v libx264 = re-encode video (fixes keyframe alignment at cut point)
				# -preset ultrafast = fastest encoding algorithm (~3x faster, slightly larger file)
				# -threads 4 = use 4 CPU threads per clip for encoding
				# -c:a aac = re-encode audio
				# NOTE: Never use -c copy here - it causes visual glitches at cut points.
				command = [
					"ffmpeg",
					"-y",
					"-i",
					video_path,
					"-ss",
					str(start),
					"-to",
					str(end),
					"-c:v",
					"libx264",
					"-preset",
					"ultrafast",
					"-threads",
					"4",
					"-c:a",
					"aac",
					str(raw_clip_path),
				]

				# Log the exact command before executing it so failures are easy to trace.
				logger.info("Running ffmpeg command: %s", " ".join(command))

				# Run ffmpeg and capture output so failures can be inspected without aborting the job.
				result = subprocess.run(command, capture_output=True, text=True)

				# Skip this clip if ffmpeg returned a non-zero exit code, but return None so other clips continue.
				if result.returncode != 0:
					logger.warning(
						"ffmpeg failed for clip %s (%s): %s",
						index,
						raw_filename,
						result.stderr.strip(),
					)
					return None

				# Log success so the caller can trace which clips were produced.
				logger.info("Successfully created raw clip file: %s", raw_filename)
			except Exception as stage_exc:
				logger.exception("Clip %s - Stage 1 failed: %s", index, stage_exc)
				return None

			# Stage 2 - Subtitle generation (non-critical)
			logger.info("Clip %s - Stage 2: Subtitle generation", index)
			subtitle_path: str | None = None
			has_subtitles = False
			try:
				subtitle_output = output_directory / f"{filename_prefix}_{index}_subs.ass"
				subtitle_result = segments_to_ass(
					segments=all_segments,
					clip_start=clip["start"],
					clip_end=clip["end"],
					output_path=str(subtitle_output),
				)
				if subtitle_result:
					subtitle_path = str(subtitle_result)
				elif subtitle_output.exists():
					subtitle_path = str(subtitle_output)
				if subtitle_path and Path(subtitle_path).exists():
					has_subtitles = True
			except Exception as stage_exc:
				logger.warning(
					"Clip %s - Stage 2 failed, continuing without subtitles: %s",
					index,
					stage_exc,
				)
				subtitle_path = None
				has_subtitles = False

			# Stage 3 - Visual enhancement (critical)
			logger.info("Clip %s - Stage 3: Visual enhancement", index)
			enhanced_filename = f"{filename_prefix}_{index}_{sanitized_label}_enhanced.mp4"
			enhanced_path = output_directory / enhanced_filename
			try:
				width, height = get_video_dimensions(str(raw_clip_path))
				if is_shorts:
					face_x = detect_face_center_x(str(raw_clip_path), 0, duration)
				else:
					face_x = 0.5

				apply_enhancements(
					input_path=str(raw_clip_path),
					output_path=str(enhanced_path),
					clip_duration=duration,
					watermark_text=config.WATERMARK_TEXT,
					subtitle_path=subtitle_path,
					is_shorts=is_shorts,
					face_center_x=face_x,
					video_width=width,
					video_height=height,
				)

				if not enhanced_path.exists():
					raise RuntimeError(f"Enhanced file not created: {enhanced_path}")
			except Exception as stage_exc:
				logger.exception("Clip %s - Stage 3 failed: %s", index, stage_exc)
				raise RuntimeError(f"Clip {index} visual enhancement failed: {stage_exc}") from stage_exc

			# Stage 4 - Add music with ducking (fallback to enhanced clip)
			logger.info("Clip %s - Stage 4: Add music with ducking", index)
			final_filename = f"{filename_prefix}_{index}_{sanitized_label}.mp4"
			final_path = output_directory / final_filename
			has_music = False
			final_video_path = final_path
			try:
				add_music_to_clip(
					video_path=str(enhanced_path),
					output_path=str(final_path),
					music_style=music_style,
					speech_segments=all_segments,
					clip_start=clip["start"],
					clip_end=clip["end"],
				)
				if not final_path.exists():
					raise RuntimeError(f"Music stage output not created: {final_path}")
				has_music = True
			except Exception as stage_exc:
				logger.warning(
					"Clip %s - Stage 4 failed, using enhanced video without music: %s",
					index,
					stage_exc,
				)
				final_video_path = enhanced_path

			# Stage 5 - Cleanup intermediate files
			logger.info("Clip %s - Stage 5: Cleanup intermediate files", index)
			for intermediate_path in [raw_clip_path, enhanced_path]:
				# Keep the file if it is being used as the final fallback output.
				if intermediate_path == final_video_path:
					continue
				try:
					intermediate_path.unlink()
				except FileNotFoundError:
					pass
				except Exception as cleanup_exc:
					logger.warning(
						"Clip %s - Failed to remove intermediate file %s: %s",
						index,
						intermediate_path,
						cleanup_exc,
					)
			logger.info("Cleaned up intermediate files for clip %s", index)

			# Stage 6 - Thumbnail generation from final output (optional, non-critical)
			logger.info("Clip %s - Stage 6: Thumbnail generation", index)
			thumbnail_filename = f"{filename_prefix}_{index}_thumb.jpg"
			thumbnail_output_path = output_directory / thumbnail_filename
			thumbnail_timestamp = duration / 2
			thumbnail_path = generate_thumbnail(
				str(final_video_path), thumbnail_timestamp, str(thumbnail_output_path)
			)

			# Return the clip metadata including optional thumbnail path
			return {
				"filename": final_video_path.name,
				"label": label,
				"start": start,
				"end": end,
				"duration": duration,
				"thumbnail_path": thumbnail_path,
				"quality_score": 0,
				"has_subtitles": has_subtitles,
				"has_music": has_music,
			}

		except FileNotFoundError as exc:
			# ffmpeg is missing — log and return None instead of crashing
			logger.error("ffmpeg not found for clip %s: %s", index, exc)
			return None
		except Exception as exc:
			# Log unexpected failures for this clip and return None
			logger.exception("Failed to cut clip %s: %s", index, exc)
			return None

	# Run all clips in parallel using ThreadPoolExecutor
	created_clips: list[dict] = []

	try:
		# Max 3 workers is safe for most machines; adjust if needed
		with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
			# Submit all clip cutting tasks to the thread pool
			futures = {
				executor.submit(cut_single_clip, clip, i): i
				for i, clip in enumerate(clips, 1)
			}

			# Collect results as they complete
			for future in concurrent.futures.as_completed(futures):
				try:
					result = future.result()
					if result is not None:
						created_clips.append(result)
				except Exception as e:
					logger.error(f"Clip cutting thread failed: {e}")

	except Exception as exc:
		# If ThreadPoolExecutor itself fails, raise
		logger.exception("ThreadPoolExecutor failed during parallel clip cutting")
		raise RuntimeError(f"Parallel clip cutting failed: {str(exc)}") from exc

	# Sort by start time so clips are in order
	created_clips.sort(key=lambda x: x["start"])

	# If nothing was created successfully, fail the job so the caller can handle it explicitly.
	if not created_clips:
		raise RuntimeError("All clips failed to cut")

	# Return the list of successfully generated clip metadata.
	return created_clips


def cut_shorts_clip(video_path: str, clip: dict, output_folder: str, index: int) -> dict | None:
	"""
	Cuts a single clip from the video in YouTube Shorts format (9:16 aspect ratio, 1080x1920).
	This is a separate output alongside the normal clip, not a replacement.

	Args:
		video_path: Path to the original video file
		clip: Dictionary with start, end, and label keys
		output_folder: Folder where the shorts clip should be saved
		index: Clip index (1-based) for filename

	Returns:
		Dictionary with shorts clip metadata on success, or None if cutting fails.
		Shorts dict includes: filename, label, start, end, duration, format
		Never raises — errors are logged and None is returned.
	"""
	try:
		# Validate input video file exists
		video_file = Path(video_path)
		if not video_file.exists():
			logger.warning(f"Video file not found for shorts clip: {video_path}")
			return None

		# Extract clip parameters
		start = float(clip["start"])
		end = float(clip["end"])
		label = str(clip.get("label", "clip"))
		sanitized_label = sanitize_label(label)
		filename = f"shorts_{index}_{sanitized_label}.mp4"

		# Prepare output directory
		output_directory = Path(output_folder)
		output_directory.mkdir(parents=True, exist_ok=True)
		output_path = output_directory / filename

		# Build the ffmpeg command for vertical Shorts format
		# -vf "crop=ih*9/16:ih,scale=1080:1920"
		#   crop=ih*9/16:ih = crop width to 9/16 of video height, keep full height
		#                      this takes the CENTER column of the landscape video
		#                      ih = input height, so width = height * (9/16)
		#   scale=1080:1920  = resize to standard Shorts resolution (1080 wide, 1920 tall)
		# -c:v libx264 = re-encode video
		# -preset ultrafast = fastest encoding algorithm (~3x faster)
		# -threads 4 = use 4 CPU threads per clip
		# -c:a aac = re-encode audio
		command = [
			"ffmpeg",
			"-y",
			"-i",
			video_path,
			"-ss",
			str(start),
			"-to",
			str(end),
			"-vf",
			"crop=ih*9/16:ih,scale=1080:1920",
			"-c:v",
			"libx264",
			"-preset",
			"ultrafast",
			"-threads",
			"4",
			"-c:a",
			"aac",
			str(output_path),
		]

		# Log the command before execution
		logger.info("Running ffmpeg command for shorts: %s", " ".join(command))

		# Run ffmpeg and capture output
		result = subprocess.run(command, capture_output=True, text=True)

		# Check if shorts clip creation succeeded
		if result.returncode != 0:
			logger.warning(
				"ffmpeg failed for shorts clip %s (%s): %s",
				index,
				filename,
				result.stderr.strip(),
			)
			return None

		# Log success
		logger.info("Successfully created shorts clip file: %s", filename)

		# Calculate clip duration
		duration = end - start

		# Return the shorts clip metadata
		return {
			"filename": filename,
			"label": label,
			"start": start,
			"end": end,
			"duration": duration,
			"format": "shorts",
		}

	except FileNotFoundError:
		logger.warning("ffmpeg not found - cannot cut shorts clip")
		return None
	except Exception as e:
		logger.warning(f"Unexpected error cutting shorts clip {index}: {str(e)}")
		return None


def cut_all_shorts(
	video_path: str,
	clips: list[dict],
	output_folder: str,
	all_segments: list[dict] | None = None,
	music_style: str = "lofi",
) -> list[dict]:
	"""
	Cuts all clips in YouTube Shorts mode using the shared clip pipeline.
	Always enables the shorts enhancement path.

	Args:
		video_path: Path to the original video file
		clips: List of clip dictionaries with start, end, and label values
		output_folder: Folder where shorts clips should be saved

	Returns:
		List of successfully created shorts clip dictionaries (sorted by start time).
		Silently skips clips that fail to cut (returns empty list if all fail).
		Never raises.
	"""
	try:
		return cut_clips(
			video_path=video_path,
			clips=clips,
			output_folder=output_folder,
			all_segments=all_segments,
			music_style=music_style,
			is_shorts=True,
		)
	except Exception as e:
		logger.warning(f"Shorts pipeline failed: {e}")
		return []


if __name__ == "__main__":
	logger.info("clipper.py loaded successfully")
