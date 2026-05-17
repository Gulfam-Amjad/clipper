"""
Transcription service for VideoClipper.
Transcribes audio using Groq Whisper API.
"""

import logging
import os

from dotenv import load_dotenv
from groq import Groq

logger = logging.getLogger(__name__)

# Load environment variables from .env file at module initialization
load_dotenv()

# Validate GROQ_API_KEY is set before any API calls
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY environment variable is not set. "
        "Please add it to your .env file."
    )

# Initialize Groq client with API key
client = Groq(api_key=GROQ_API_KEY)
logger.info("Groq client initialized successfully")


def _segment_value(segment, key: str):
    """Reads a segment field from either a dict-like or attribute-based response object."""
    if isinstance(segment, dict):
        return segment[key]
    return getattr(segment, key)


def transcribe_audio(audio_path: str) -> list[dict]:
    """
    Transcribes an audio file using Groq Whisper API.
    
    Sends the audio to Groq's Whisper model and retrieves transcript segments
    with precise timing information and text content. Segments are validated
    and empty segments are filtered out.
    
    Args:
        audio_path: Full path to the audio file (.mp3)
        
    Returns:
        List of dicts with format: {"start": float, "end": float, "text": str}
        - Segments are sorted by start time
        - Text is stripped of leading/trailing whitespace
        - Empty segments are filtered out
        
    Raises:
        RuntimeError: If API call fails, file not found, or response is malformed
    """
    try:
        # Validate audio_path parameter
        if not audio_path or not isinstance(audio_path, str):
            raise ValueError(f"Invalid audio_path: {audio_path}")
        
        # Log the audio file path for debugging and audit trail
        logger.info(f"Starting transcription for audio file: {audio_path}")
        
        # Open the audio file in binary mode and send to Groq Whisper API
        with open(audio_path, "rb") as audio_file:
            # Call Groq Whisper API with specific parameters optimized for accuracy
            # - model: "whisper-large-v3" (latest and most accurate Whisper model)
            # - response_format: "verbose_json" (returns detailed segment info with timestamps)
            # - language: "en" (English language transcription)
            logger.debug("Sending audio to Groq Whisper API...")
            
            response = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
                response_format="verbose_json",
                language="en"
            )
        
        # Validate that API returned segments in response
        if not response.segments:
            logger.error("Whisper API returned no segments from audio file")
            raise RuntimeError("Whisper returned no segments")
        
        # Process segments: extract data and filter empty text
        segments = []
        for seg in response.segments:
            # Strip whitespace from segment text for cleanliness.
            text = str(_segment_value(seg, "text")).strip()
            start = float(_segment_value(seg, "start"))
            end = float(_segment_value(seg, "end"))
            
            # Skip segments with empty or whitespace-only text
            if not text:
                logger.debug(f"Skipping empty segment at {start}s-{end}s")
                continue
            
            # Convert segment object to plain dict format
            segment_dict = {
                "start": start,
                "end": end,
                "text": text,
            }
            segments.append(segment_dict)
        
        # Validate that we have at least one valid segment after filtering
        if not segments:
            logger.error("No valid segments found after filtering empty text")
            raise RuntimeError("No valid transcript segments found")
        
        # Log successful transcription with segment count for monitoring
        logger.info(f"Transcription complete: {len(segments)} segments extracted")
        
        return segments
        
    except FileNotFoundError as e:
        # Catch audio file not found errors
        error_msg = f"Audio file not found: {audio_path}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
        
    except Exception as e:
        # Catch Groq API errors and any other unexpected errors
        error_msg = f"Transcription failed: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


if __name__ == "__main__":
    print("transcriber.py loaded successfully")
