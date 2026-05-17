"""
Video clip cutting service for VideoClipper.
This module turns clip timestamps into individual video files using ffmpeg.
"""

import logging
import subprocess
from pathlib import Path

from utils.validators import sanitize_label


logger = logging.getLogger(__name__)


def cut_clips(video_path: str, clips: list[dict], output_folder: str) -> list[dict]:
	"""
	Cuts a source video into individual clip files using ffmpeg.

	Args:
		video_path: Path to the original uploaded video.
		clips: List of clip dictionaries with start, end, and label values.
		output_folder: Folder where the generated clip files should be saved.

	Returns:
		A list of dictionaries describing each successfully created clip.

	Raises:
		RuntimeError: If ffmpeg is not available or if every clip fails.
	"""
	# Prepare the output directory and the list that will collect successful clips.
	output_directory = Path(output_folder)
	output_directory.mkdir(parents=True, exist_ok=True)
	created_clips: list[dict] = []

	# Process each clip sequentially so one ffmpeg job runs at a time.
	for index, clip in enumerate(clips, start=1):
		try:
			# Read the clip fields and derive the output filename from the label.
			start = float(clip["start"])
			end = float(clip["end"])
			label = str(clip.get("label", "clip"))
			sanitized_label = sanitize_label(label)
			filename = f"clip_{index}_{sanitized_label}.mp4"
			output_path = output_directory / filename

			# Build the ffmpeg command that re-encodes video and audio for clean cuts.
			# -y = overwrite if exists
			# -ss {start} = seek to start time in seconds
			# -to {end} = stop at end time in seconds
			# -c:v libx264 = re-encode video (fixes keyframe alignment at cut point)
			# -c:a aac = re-encode audio
			# NOTE: Never use -c copy here — it causes visual glitches at cut points.
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
				"-c:a",
				"aac",
				str(output_path),
			]

			# Log the exact command before executing it so failures are easy to trace.
			logger.info("Running ffmpeg command: %s", " ".join(command))

			# Run ffmpeg and capture output so failures can be inspected without aborting the job.
			result = subprocess.run(command, capture_output=True, text=True)

			# Skip this clip if ffmpeg returned a non-zero exit code, but keep processing others.
			if result.returncode != 0:
				logger.warning(
					"ffmpeg failed for clip %s (%s): %s",
					index,
					filename,
					result.stderr.strip(),
				)
				continue

			# Record the successful clip using the requested output structure.
			duration = end - start
			created_clips.append(
				{
					"filename": filename,
					"label": label,
					"start": start,
					"end": end,
					"duration": duration,
				}
			)

			# Log success so the caller can trace which clips were produced.
			logger.info("Successfully created clip file: %s", filename)

		except FileNotFoundError as exc:
			# Surface a clear error when ffmpeg is missing from the environment.
			raise RuntimeError("ffmpeg not found") from exc
		except Exception as exc:
			# Log unexpected failures for this clip and continue with the remaining clips.
			logger.exception("Failed to cut clip %s: %s", index, exc)
			continue

	# If nothing was created successfully, fail the job so the caller can handle it explicitly.
	if not created_clips:
		raise RuntimeError("All clips failed to cut")

	# Return the list of successfully generated clip metadata.
	return created_clips


if __name__ == "__main__":
	print("clipper.py loaded successfully")
