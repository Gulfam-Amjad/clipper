"""
Validation utilities for VideoClipper.
Handles file validation and string sanitization.
"""

import logging
import re
from typing import Tuple

from ..config import config

logger = logging.getLogger(__name__)

# Constants
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
MAX_FILE_SIZE_BYTES = int(config.MAX_FILE_SIZE_MB * 1024 * 1024)


def validate_video_file(filename: str, file_size_bytes: int) -> Tuple[bool, str]:
    """
    Validates a video file based on extension, size, and emptiness.
    
    Args:
        filename: The name of the file to validate
        file_size_bytes: The size of the file in bytes
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
        - (True, "") if valid
        - (False, "error message") if invalid
    """
    try:
        # Check if filename is empty
        if not filename or not isinstance(filename, str) or not filename.strip():
            error_msg = "Filename cannot be empty"
            logger.warning(error_msg)
            return (False, error_msg)
        
        # Check if file is empty
        if file_size_bytes <= 0:
            error_msg = "File size must be greater than 0 bytes"
            logger.warning(f"Invalid file size for {filename}: {file_size_bytes} bytes")
            return (False, error_msg)
        
        # Check file extension
        file_ext = ""
        if "." in filename:
            file_ext = "." + filename.rsplit(".", 1)[-1].lower()
        
        if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
            error_msg = f"File extension '{file_ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
            logger.warning(f"Invalid extension for {filename}: {file_ext}")
            return (False, error_msg)
        
        # Check file size
        max_size_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        file_size_mb = file_size_bytes / (1024 * 1024)
        
        if file_size_bytes > MAX_FILE_SIZE_BYTES:
            error_msg = f"File size {file_size_mb:.1f}MB exceeds limit of {max_size_mb:.0f}MB"
            logger.warning(f"File too large: {filename} ({file_size_mb:.1f}MB)")
            return (False, error_msg)
        
        logger.info(f"Video file validated successfully: {filename} ({file_size_mb:.1f}MB)")
        return (True, "")
        
    except Exception as e:
        error_msg = f"Error validating video file: {str(e)}"
        logger.error(error_msg)
        return (False, error_msg)


def sanitize_label(label: str) -> str:
    """
    Sanitizes a string to be safe for use in a filename.
    
    - Replaces spaces with underscores
    - Removes non-alphanumeric characters (except underscore and hyphen)
    - Truncates to 40 characters max
    - Returns "clip" as fallback if result is empty
    
    Args:
        label: The string to sanitize
        
    Returns:
        Sanitized string safe for use in filenames
    """
    try:
        if not isinstance(label, str):
            label = str(label)
        
        # Replace spaces with underscores
        sanitized = label.replace(" ", "_")
        
        # Remove any character that is not alphanumeric, underscore, or hyphen
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", sanitized)
        
        # Truncate to 40 characters
        sanitized = sanitized[:40]
        
        # Return "clip" as fallback if empty
        if not sanitized:
            sanitized = "clip"
            logger.debug(f"Label was empty after sanitization, using fallback: {sanitized}")
        else:
            logger.debug(f"Sanitized label: '{label}' -> '{sanitized}'")
        
        return sanitized
        
    except Exception as e:
        logger.error(f"Error sanitizing label: {str(e)}")
        return "clip"


def validate_clip_bounds(clips: list[dict]) -> list[dict]:
    """
    Validates clip timing rules before ffmpeg cuts are attempted.

    Ensures each clip has required fields, uses non-negative timestamps,
    has a positive duration, and does not overlap with the next clip.
    Clips that are shorter than 30s are skipped (logged) rather than
    causing the whole validation to fail.
    """
    try:
        normalized_clips: list[dict] = []

        # Validate each clip individually before checking ordering constraints.
        for index, clip in enumerate(clips):
            if not isinstance(clip, dict):
                raise ValueError(f"Clip {index} must be a dict")

            if "start" not in clip or "end" not in clip or "label" not in clip:
                raise ValueError(f"Clip {index} is missing required fields")

            start = float(clip["start"])
            end = float(clip["end"])

            if start < 0 or end < 0:
                raise ValueError(f"Clip {index} cannot use negative timestamps")
            if end <= start:
                raise ValueError(f"Clip {index} end must be greater than start")

            duration = end - start
            if duration < 30:
                logger.warning(
                    f"Clip {index} duration {duration:.1f}s is below minimum 30s — skipping"
                )
                continue

            if duration > 180:
                logger.warning(
                    f"Clip {index} duration {duration:.1f}s exceeds 180s — capping to 180s"
                )
                end = start + 180.0

            normalized_clips.append(
                {
                    "start": start,
                    "end": end,
                    "label": str(clip["label"]),
                }
            )

        # Check for overlaps after sorting clips by their starting time.
        sorted_clips = sorted(normalized_clips, key=lambda clip: clip["start"])
        for index in range(len(sorted_clips) - 1):
            current_clip = sorted_clips[index]
            next_clip = sorted_clips[index + 1]
            if current_clip["end"] > next_clip["start"]:
                raise ValueError(f"Clips {index} and {index + 1} overlap")

        return normalized_clips

    except Exception as exc:
        logger.error(f"Error validating clip bounds: {str(exc)}")
        raise
