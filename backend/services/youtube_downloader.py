"""
YouTube downloader service for VideoClipper.
Downloads videos from YouTube URLs using yt-dlp, validates URLs, retrieves metadata.
Handles YouTube's changing protocols automatically with active yt-dlp maintenance.
"""

import logging
import os
import re
from pathlib import Path

try:
	import yt_dlp
except ImportError:
	yt_dlp = None


logger = logging.getLogger(__name__)


def is_valid_youtube_url(url: str) -> bool:
	"""
	Validates if a URL is a valid YouTube URL without making network requests.
	Accepts standard YouTube and YouTube Shorts patterns.

	Args:
		url: URL string to validate

	Returns:
		True if URL matches valid YouTube patterns, False otherwise
	"""
	try:
		if not url or not isinstance(url, str):
			return False

		# Regex pattern matching common YouTube URL formats:
		# 1. https://www.youtube.com/watch?v=VIDEOID
		# 2. https://youtu.be/VIDEOID
		# 3. https://youtube.com/shorts/VIDEOID
		# 4. https://www.youtube.com/shorts/VIDEOID
		youtube_pattern = r"^https?://(?:www\.)?(?:youtube\.com|youtu\.be)(?:/watch\?v=|/shorts/|/embed/|/)[\w-]+"

		return bool(re.match(youtube_pattern, url.strip(), re.IGNORECASE))

	except Exception as e:
		logger.warning(f"Error validating YouTube URL: {e}")
		return False


def validate_youtube_url(url: str) -> tuple[bool, str]:
	"""
	Validates a YouTube URL and returns validation status with error message if invalid.
	Uses is_valid_youtube_url() for format checking only (no network calls).

	Args:
		url: URL string to validate

	Returns:
		Tuple of (is_valid: bool, error_message: str)
		On success: (True, "")
		On failure: (False, "error description")
	"""
	try:
		if not url:
			return (False, "URL cannot be empty")

		if not isinstance(url, str):
			return (False, "URL must be a string")

		if is_valid_youtube_url(url):
			return (True, "")
		else:
			return (False, "Invalid YouTube URL format. Expected: youtube.com/watch?v=..., youtu.be/..., or youtube.com/shorts/...")

	except Exception as e:
		return (False, f"Validation error: {str(e)}")


def get_video_info(url: str) -> dict:
	"""
	Retrieves video metadata from YouTube WITHOUT downloading.
	Uses yt-dlp to fetch information only.

	Args:
		url: YouTube video URL

	Returns:
		Dict with keys: title, duration_seconds, uploader, view_count

	Raises:
		RuntimeError: If metadata extraction fails
	"""
	try:
		if yt_dlp is None:
			raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp")

		# yt-dlp options for metadata extraction (no download)
		ydl_opts = {
			"quiet": True,
			"no_warnings": True,
			"extract_flat": False,
		}

		logger.debug(f"Extracting metadata from: {url}")

		with yt_dlp.YoutubeDL(ydl_opts) as ydl:
			info = ydl.extract_info(url, download=False)

		# Parse and return relevant metadata
		video_info = {
			"title": info.get("title", "Unknown"),
			"duration_seconds": info.get("duration", 0),
			"uploader": info.get("uploader", "Unknown"),
			"view_count": info.get("view_count", 0),
		}

		logger.debug(f"Retrieved metadata: title='{video_info['title']}', duration={video_info['duration_seconds']}s")

		return video_info

	except Exception as e:
		error_msg = str(e)
		logger.error(f"Failed to get video info from {url}: {error_msg}")
		raise RuntimeError(f"Failed to retrieve video metadata: {error_msg}")


def download_youtube_video(url: str, output_folder: str) -> str:
	"""
	Downloads a video from YouTube to the output folder.
	Returns the local path to the downloaded file.
	Automatically handles format selection, codec conversion, and file size limits.

	Args:
		url: YouTube video URL
		output_folder: Directory where video will be saved

	Returns:
		Absolute path to the downloaded .mp4 file

	Raises:
		RuntimeError: If download fails or output file cannot be found
	"""
	try:
		if yt_dlp is None:
			raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp")

		# Ensure output folder exists
		output_dir = Path(output_folder)
		output_dir.mkdir(parents=True, exist_ok=True)

		logger.info(f"Downloading: {url}")

		# yt-dlp options for best quality video under 720p height with MP4 format
		# Downloads the best video stream (h.264/h.265) combined with best audio
		# Falls back to best single-file format if separate streams unavailable
		# format selector breakdown:
		#   bestvideo[height<=720][ext=mp4] = best video ≤720p in mp4 container
		#   bestaudio[ext=m4a] = best audio in m4a container
		#   best[height<=720][ext=mp4] = if above fails, use best overall ≤720p
		#   best[height<=720] = fallback if mp4 unavailable
		ydl_opts = {
			"format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
			"outtmpl": str(output_dir / "video.%(ext)s"),
			"quiet": True,
			"no_warnings": True,
			"noplaylist": True,  # Only download single video, never playlists
			"max_filesize": 500 * 1024 * 1024,  # 500MB file size limit
			"postprocessors": [
				{
					"key": "FFmpegVideoConvertor",
					"preferedformat": "mp4",  # Always save final output as mp4
				}
			],
		}

		# Perform the download
		with yt_dlp.YoutubeDL(ydl_opts) as ydl:
			info = ydl.extract_info(url, download=True)
			downloaded_filename = ydl.prepare_filename(info)

		# Look for the downloaded file
		expected_path = output_dir / "video.mp4"

		if expected_path.exists():
			logger.info(f"Download complete: {expected_path}")
			return str(expected_path)

		# Fallback: search for any .mp4 file in the output folder
		mp4_files = list(output_dir.glob("*.mp4"))
		if mp4_files:
			found_file = mp4_files[0]
			logger.info(f"Download complete: {found_file}")
			return str(found_file)

		# Video file not found
		raise RuntimeError("Download completed but output file (video.mp4) not found in output folder")

	except yt_dlp.utils.DownloadError as e:
		# Download error from yt-dlp (URL invalid, video unavailable, etc.)
		error_msg = str(e).replace("ERROR: ", "").strip()
		logger.error(f"YouTube download error: {error_msg}")
		raise RuntimeError(f"YouTube download failed: {error_msg}")

	except yt_dlp.utils.MaxDownloadsReached:
		# File size limit exceeded
		logger.error("Downloaded file exceeds 500MB size limit")
		raise RuntimeError("File too large (exceeds 500MB limit)")

	except Exception as e:
		error_msg = str(e)
		logger.error(f"Failed to download video from {url}: {error_msg}")
		raise RuntimeError(f"Failed to download video: {error_msg}")


# Test module on import
if __name__ == "__main__":
	logger.info("youtube_downloader.py loaded OK")
