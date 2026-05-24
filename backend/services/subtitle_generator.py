"""
Subtitle generation service for VideoClipper.
Converts Whisper transcript segments into ASS subtitle files for rich formatting support.
Handles timing adjustment, style configuration, and seamless integration with video clips.
"""

import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def seconds_to_ass_time(seconds: float) -> str:
	"""
	Converts seconds to ASS (Advanced SubStation Alpha) time format.
	ASS format: H:MM:SS.cc where cc is centiseconds (0-99).

	Args:
		seconds: Time in seconds as float

	Returns:
		String in format "H:MM:SS.cc"
		Example: 65.5 seconds → "0:01:05.50"
	"""
	# Calculate hours, minutes, seconds, and centiseconds
	hours = int(seconds // 3600)
	remaining = seconds % 3600
	minutes = int(remaining // 60)
	secs = int(remaining % 60)
	centiseconds = int((seconds % 1) * 100)

	# Format with zero-padding for minutes and seconds, but not hours
	return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def segments_to_ass(segments: list[dict], clip_start: float, clip_end: float, output_path: str) -> str | None:
	"""
	Converts Whisper transcript segments to an ASS subtitle file.
	Filters segments to only include those within the clip timeframe and adjusts timestamps
	to be relative to the clip start (so clip starts at 0:00).

	Args:
		segments: List of segment dicts with keys: "start" (float), "end" (float), "text" (str)
		clip_start: Clip start time in original video seconds
		clip_end: Clip end time in original video seconds
		output_path: Where to save the .ass subtitle file

	Returns:
		output_path on success, None on error
	"""
	try:
		# Validate inputs
		if not segments or not isinstance(segments, list):
			logger.warning("No segments provided for subtitle generation")
			return None

		if clip_end <= clip_start:
			logger.warning(f"Invalid clip range: {clip_start} to {clip_end}")
			return None

		# Build ASS file header with metadata
		ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2.5,1.5,2,30,30,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

		# Filter and convert segments within clip range
		dialogue_lines = []
		segments_added = 0

		for segment in segments:
			try:
				# Extract segment data
				seg_start = float(segment.get("start", 0))
				seg_end = float(segment.get("end", 0))
				text = str(segment.get("text", "")).strip()

				# Skip empty text
				if not text:
					continue

				# Check if segment overlaps with clip range
				if seg_end <= clip_start or seg_start >= clip_end:
					continue

				# Adjust segment times to be relative to clip start
				adjusted_start = max(0, seg_start - clip_start)
				adjusted_end = min(clip_end - clip_start, seg_end - clip_start)

				# Convert to ASS time format
				start_time = seconds_to_ass_time(adjusted_start)
				end_time = seconds_to_ass_time(adjusted_end)

				# Clean text: remove extra spaces, normalize
				cleaned_text = " ".join(text.split())

				# Build dialogue line in ASS format
				# Format: Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
				dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{cleaned_text}"
				dialogue_lines.append(dialogue_line)
				segments_added += 1

			except (KeyError, ValueError, TypeError) as e:
				logger.warning(f"Error processing segment: {e}, skipping")
				continue

		# Add all dialogue lines to ASS content
		ass_content += "\n".join(dialogue_lines)

		# Write to file
		output_file = Path(output_path)
		output_file.parent.mkdir(parents=True, exist_ok=True)
		output_file.write_text(ass_content, encoding="utf-8")

		logger.info(f"Generated ASS subtitle file: {output_path} ({segments_added} segments)")
		return output_path

	except Exception as e:
		logger.error(f"Error generating ASS subtitles: {e}")
		return None


# Test module on import
if __name__ == "__main__":
	logger.info("subtitle_generator.py loaded OK")
