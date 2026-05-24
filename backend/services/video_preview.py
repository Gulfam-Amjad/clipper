"""Video preview utilities for VideoClipper.

Generate a quick thumbnail and basic metadata for uploaded videos so the
frontend can show a preview before processing starts.
"""

import subprocess
import logging
import os
import pathlib
import json
from PIL import Image
import io
import base64


logger = logging.getLogger(__name__)


# Extract basic metadata for a video using ffprobe.
def get_video_metadata(video_path: str) -> dict:
    try:
        logger.info("Getting video metadata for %s", video_path)

        # Run ffprobe to get JSON output describing streams and format
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            video_path,
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout:
            logger.warning("ffprobe failed for %s: %s", video_path, result.stderr.strip())
            raise RuntimeError("ffprobe failed")

        probe = json.loads(result.stdout)

        # Safe defaults
        duration_seconds = 0.0
        width = 0
        height = 0
        fps = 0.0
        file_size_mb = 0.0
        fmt = "unknown"
        has_audio = False

        # Parse format block
        fmt_block = probe.get("format") or {}
        try:
            duration_seconds = float(fmt_block.get("duration") or 0.0)
        except Exception:
            duration_seconds = 0.0
        try:
            size_bytes = int(fmt_block.get("size") or 0)
            file_size_mb = float(size_bytes) / (1024 * 1024)
        except Exception:
            file_size_mb = 0.0
        try:
            fmt_name = str(fmt_block.get("format_name") or "")
            fmt = fmt_name.split(",")[0] if fmt_name else "unknown"
        except Exception:
            fmt = "unknown"

        # Parse streams for video/audio info
        streams = probe.get("streams") or []
        for s in streams:
            try:
                if s.get("codec_type") == "video":
                    width = int(s.get("width") or width or 0)
                    height = int(s.get("height") or height or 0)
                    # r_frame_rate is usually like "30000/1001" or "25/1"
                    fps_str = s.get("r_frame_rate") or s.get("avg_frame_rate") or "0/1"
                    if isinstance(fps_str, str) and "/" in fps_str:
                        num, den = fps_str.split("/")
                        try:
                            fps = float(num) / float(den) if int(den) != 0 else 0.0
                        except Exception:
                            fps = 0.0
                elif s.get("codec_type") == "audio":
                    has_audio = True
            except Exception:
                # Non-fatal per-stream parsing errors
                logger.debug("Error parsing stream info: %s", s)
                continue

        # Human friendly duration string M:SS
        try:
            total_seconds = int(duration_seconds or 0)
            mins = total_seconds // 60
            secs = total_seconds % 60
            duration_str = f"{mins}:{secs:02d}"
        except Exception:
            duration_str = "0:00"

        metadata = {
            "duration_seconds": float(duration_seconds or 0.0),
            "duration_str": duration_str,
            "width": int(width or 0),
            "height": int(height or 0),
            "fps": float(fps or 0.0),
            "file_size_mb": float(round(file_size_mb, 2)),
            "format": fmt,
            "has_audio": bool(has_audio),
        }

        logger.debug("Parsed metadata for %s: %s", video_path, metadata)
        return metadata

    except Exception as exc:
        logger.warning("Failed to get metadata for %s: %s", video_path, exc)
        # Return safe defaults on any error
        return {
            "duration_seconds": 0.0,
            "duration_str": "0:00",
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "file_size_mb": 0.0,
            "format": "unknown",
            "has_audio": False,
        }


# Generate a single JPEG thumbnail using ffmpeg at the requested timestamp.
def generate_preview_thumbnail(video_path: str, output_path: str, timestamp: float = 2.0) -> str | None:
    try:
        logger.info("Generating preview thumbnail for %s at %.2fs", video_path, timestamp)

        # Ensure parent directory exists
        out_path = pathlib.Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        vf_expr = (
            'scale=640:360:force_original_aspect_ratio=decrease,'
            'pad=640:360:(ow-iw)/2:(oh-ih)/2'
        )

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
            "3",
            "-vf",
            vf_expr,
            str(output_path),
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("ffmpeg thumbnail generation failed for %s: %s", video_path, result.stderr.strip())
            return None

        if not out_path.exists():
            logger.warning("Thumbnail file not created: %s", output_path)
            return None

        # Optionally re-open with PIL to ensure correct JPEG format and quality
        try:
            with Image.open(out_path) as im:
                rgb = im.convert("RGB")
                rgb.save(out_path, format="JPEG", quality=85)
        except Exception:
            # If PIL processing fails, the ffmpeg-generated file is likely OK.
            logger.debug("PIL post-processing for thumbnail failed, continuing with raw file")

        logger.info("Thumbnail generated: %s", output_path)
        return str(output_path)

    except Exception as exc:
        logger.warning("Failed to generate thumbnail for %s: %s", video_path, exc)
        return None


# Create a base64 data URI for the preview thumbnail so the frontend can show it inline.
def get_preview_thumbnail_base64(video_path: str, timestamp: float = 2.0) -> str | None:
    temp_path = f"{video_path}_preview_thumb.jpg"
    try:
        thumb = generate_preview_thumbnail(video_path, temp_path, timestamp=timestamp)
        if not thumb:
            return None

        # Read bytes and encode as base64 data URI
        with open(thumb, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        uri = f"data:image/jpeg;base64,{b64}"

        return uri

    except Exception as exc:
        logger.warning("Failed to create base64 thumbnail for %s: %s", video_path, exc)
        return None

    finally:
        # Clean up temporary file if it exists
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


# Combine metadata and thumbnail and return preview payload for the frontend.
def get_full_video_preview(video_path: str) -> dict:
    try:
        logger.info("Creating full preview for %s", video_path)

        metadata = get_video_metadata(video_path)
        thumbnail = get_preview_thumbnail_base64(video_path, timestamp=2.0)

        warnings = []
        duration = metadata.get("duration_seconds", 0.0)
        width = metadata.get("width", 0)
        has_audio = metadata.get("has_audio", False)

        if not has_audio:
            warnings.append("No audio track detected")
        if duration < 60 and duration > 0:
            warnings.append("Video is very short (under 60 seconds)")
        if duration == 0:
            warnings.append("Could not read video duration or file may be invalid")
        if duration > 1800:
            warnings.append("Video is very long — processing may take 10+ minutes")
        if width < 480 and width > 0:
            warnings.append("Low resolution video")

        is_valid = bool(duration > 5)

        payload = {
            "metadata": metadata,
            "thumbnail_base64": thumbnail,
            "is_valid": is_valid,
            "warnings": warnings,
        }

        logger.debug("Preview payload for %s: %s", video_path, {"meta": metadata, "thumb": bool(thumbnail)})
        return payload

    except Exception as exc:
        logger.exception("Failed to build full preview for %s: %s", video_path, exc)
        # Never raise — always return a safe payload
        return {
            "metadata": {
                "duration_seconds": 0.0,
                "duration_str": "0:00",
                "width": 0,
                "height": 0,
                "fps": 0.0,
                "file_size_mb": 0.0,
                "format": "unknown",
                "has_audio": False,
            },
            "thumbnail_base64": None,
            "is_valid": False,
            "warnings": ["Preview generation failed"],
        }


if __name__ == "__main__":
    logger.info("video_preview.py loaded OK")
