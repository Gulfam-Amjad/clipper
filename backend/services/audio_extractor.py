"""
Audio extraction service for VideoClipper.
Extracts audio from video files using ffmpeg and saves as MP3.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_audio(video_path: str, output_path: str) -> str:
    """
    Extracts audio from a video file and saves it as MP3.
    
    Uses ffmpeg with specific parameters optimized for speech recognition:
    - 16kHz sample rate (Whisper API requirement)
    - Mono channel (reduces file size)
    - MP3 codec (compatible format)
    
    Args:
        video_path: Full path to the input video file
        output_path: Full path where audio should be saved as MP3
        
    Returns:
        output_path string on success
        
    Raises:
        RuntimeError: If ffmpeg fails, is not installed, or file not found
    """
    try:
        # Validate input video file exists
        video_file = Path(video_path)
        if not video_file.exists():
            raise RuntimeError(f"Input video file not found: {video_path}")
        
        logger.debug(f"Input video file verified: {video_path}")
        
        # Construct ffmpeg command with all required flags
        # -y         = overwrite output if it exists
        # -i         = input file
        # -vn        = no video stream (audio only)
        # -acodec mp3 = encode as MP3 codec
        # -ar 16000  = 16kHz sample rate (Whisper API requirement)
        # -ac 1      = mono channel (reduces file size, Whisper handles mono)
        # -b:a 32k   = 32kbps bitrate (sufficient for speech, ~4x file size reduction)
        ffmpeg_command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "mp3",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-b:a",
            "32k",
            output_path,
        ]
        
        # Log the full command before execution for debugging
        logger.info(f"Executing ffmpeg: {' '.join(ffmpeg_command)}")
        
        # Run ffmpeg with subprocess, capturing output
        result = subprocess.run(
            ffmpeg_command,
            capture_output=True,
            text=True,
        )
        
        # Check if ffmpeg command succeeded (return code 0)
        if result.returncode != 0:
            error_message = result.stderr or "Unknown ffmpeg error"
            logger.error(f"ffmpeg extraction failed: {error_message}")
            raise RuntimeError(f"ffmpeg audio extraction failed: {error_message}")
        
        # Verify output file was created
        output_file = Path(output_path)
        if not output_file.exists():
            raise RuntimeError(f"Audio extraction completed but output file not found: {output_path}")
        
        # Log success with file size information
        file_size_mb = output_file.stat().st_size / (1024 * 1024)
        logger.info(f"Audio extracted successfully: {output_path} ({file_size_mb:.2f}MB)")
        
        return output_path
        
    except FileNotFoundError as e:
        # Catch ffmpeg not installed or not in PATH
        error_msg = "ffmpeg is not installed or not in PATH"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
        
    except Exception as e:
        # Catch any other unexpected errors
        logger.error(f"Unexpected error during audio extraction: {str(e)}")
        raise


if __name__ == "__main__":
    print("audio_extractor.py loaded successfully")
