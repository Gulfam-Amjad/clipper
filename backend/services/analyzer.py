"""
Transcript analysis service for VideoClipper.
Uses Groq LLM to identify key video clips from transcript segments.
"""

import json
import logging
import os

from dotenv import load_dotenv
from groq import Groq

from utils.validators import validate_clip_bounds

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
logger.info("Groq client initialized for analyzer")


def _seconds_to_mmss(seconds: float) -> str:
    """
    Converts seconds to MM:SS format.
    
    Args:
        seconds: Time in seconds as float
        
    Returns:
        Formatted string "MM:SS"
    """
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def format_transcript(segments: list[dict]) -> str:
    """
    Formats transcript segments into a readable string for LLM analysis.
    
    Converts each segment into "[MM:SS → MM:SS] Text" format so the LLM
    can easily identify key moments by their timing and content.
    
    Args:
        segments: List of {"start": float, "end": float, "text": str}
        
    Returns:
        Formatted string with each line as a segment in readable format
    """
    try:
        lines = []
        for seg in segments:
            # Convert float seconds to MM:SS format for readability
            start_str = _seconds_to_mmss(seg["start"])
            end_str = _seconds_to_mmss(seg["end"])
            text = seg["text"]
            
            # Format each segment as "[START → END] Text"
            line = f"[{start_str} → {end_str}] {text}"
            lines.append(line)
        
        # Join all segments with newlines for readability
        formatted = "\n".join(lines)
        logger.debug(f"Formatted {len(segments)} segments for LLM analysis")
        return formatted
    except Exception as e:
        logger.error(f"Error formatting transcript: {str(e)}")
        raise


def parse_llm_response(response_text: str) -> list[dict]:
    """
    Parses and validates LLM response as JSON array of clips.
    
    Removes markdown code fences if present, validates JSON structure,
    ensures all clips have required fields with correct types and values.
    
    Args:
        response_text: Raw text response from LLM
        
    Returns:
        List of dicts: [{"start": float, "end": float, "label": str}, ...]
        
    Raises:
        ValueError: If parsing fails or any validation check fails
    """
    try:
        # Strip and clean the response text
        cleaned = response_text.strip()
        
        # Remove markdown code fences if present (```json ... ``` or ``` ... ```)
        if cleaned.startswith("```"):
            # Remove opening fence (either ```json or just ```)
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            else:
                cleaned = cleaned[3:]
            
            # Remove closing fence
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        
        cleaned = cleaned.strip()
        logger.debug(f"Cleaned LLM response for parsing: {cleaned[:100]}...")
        
        # Parse JSON from cleaned text
        clips = json.loads(cleaned)
        
        # Validate that result is a list
        if not isinstance(clips, list):
            raise ValueError("LLM response must be a JSON array, got: " + str(type(clips)))
        
        # Validate each clip in the array
        for i, clip in enumerate(clips):
            # Check clip is a dict
            if not isinstance(clip, dict):
                raise ValueError(f"Clip {i} is not a dict, got: {type(clip)}")
            
            # Check all required fields are present
            if "start" not in clip:
                raise ValueError(f"Clip {i} missing required 'start' field")
            if "end" not in clip:
                raise ValueError(f"Clip {i} missing required 'end' field")
            if "label" not in clip:
                raise ValueError(f"Clip {i} missing required 'label' field")
            
            # Validate field types
            if not isinstance(clip["start"], (int, float)):
                raise ValueError(f"Clip {i} 'start' must be number, got {type(clip['start'])}")
            if not isinstance(clip["end"], (int, float)):
                raise ValueError(f"Clip {i} 'end' must be number, got {type(clip['end'])}")
            if not isinstance(clip["label"], str):
                raise ValueError(f"Clip {i} 'label' must be string, got {type(clip['label'])}")
            
            # Validate start < end for valid time range
            if clip["start"] >= clip["end"]:
                raise ValueError(
                    f"Clip {i} has invalid time range: start ({clip['start']}) >= end ({clip['end']})"
                )
        
        # All validation passed
        logger.info(f"Successfully parsed and validated {len(clips)} clips from LLM response")
        return validate_clip_bounds(clips)
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in LLM response: {str(e)}") from e
    except ValueError as e:
        raise


def analyze_transcript(segments: list[dict], guidance: str = None) -> list[dict]:
    """
    Analyzes transcript segments to identify 4-5 key video clips.
    
    Uses Groq Llama 3.3 70B LLM to intelligently extract the most important
    segments. Can operate in two modes:
    - Auto Mode (guidance=None): Identifies key concepts automatically
    - Guided Mode (guidance set): Focuses on user-specified topics
    
    Includes automatic retry logic with progressive strictness:
    - First attempt: standard LLM prompt
    - If parse fails: retry with stricter JSON-only instructions
    - If both fail: raise RuntimeError
    
    Args:
        segments: List of {"start": float, "end": float, "text": str}
        guidance: Optional user instruction string (None = Auto Mode)
        
    Returns:
        List of 4-5 dicts: [{"start": float, "end": float, "label": str}, ...]
        
    Raises:
        RuntimeError: If LLM analysis fails or JSON parsing fails twice
    """
    try:
        # Validate input segments
        if not segments or len(segments) == 0:
            raise ValueError("No segments provided for analysis")
        
        if not isinstance(segments, list):
            raise TypeError(f"Segments must be list, got {type(segments)}")
        
        # Determine mode and log it for tracking
        if guidance:
            mode = "Guided"
            # Validate guidance is string and within reasonable length
            if not isinstance(guidance, str):
                guidance = str(guidance)
            if len(guidance) > 500:
                guidance = guidance[:500]
            logger.info(f"Analyzer running in Guided Mode with user instruction: {guidance[:50]}...")
        else:
            mode = "Auto"
            logger.info("Analyzer running in Auto Mode")
        
        # Format the transcript segments into readable LLM input
        formatted_transcript = format_transcript(segments)
        
        # Construct system prompt for Auto/Guided mode
        # This prompt guides the LLM to return only JSON with specific requirements
        system_prompt = """You are a video analysis AI. Your job is to identify the 4 to 5 most 
important, information-dense, and valuable segments from a video transcript.

Rules:
- Each clip must be between 30 seconds and 3 minutes long
- Clips must NOT overlap with each other
- Prefer segments where the speaker explains a key concept, gives a main point, 
  or delivers important information
- Return ONLY a valid JSON array. No explanation. No markdown. No extra text.
- Timestamps must be in seconds as floats (e.g. 45.0, not "0:45")

Output format (return ONLY this JSON, nothing else):
[
  {"start": 45.2, "end": 98.7, "label": "Main concept explained"},
  {"start": 134.0, "end": 187.3, "label": "Key example given"}
]"""
        
        # Build user message with formatted transcript
        user_message = f"Analyze this transcript and identify the best clips:\n\n{formatted_transcript}"
        
        # Append guided mode instructions if user provided guidance
        if guidance:
            user_message += f"\n\nUser guidance: {guidance}\nUse this guidance to select the most relevant segments matching what the user described."
        
        # ─── FIRST LLM CALL ATTEMPT ───
        logger.debug("Calling Groq LLM for clip analysis (attempt 1/2)...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        
        # Extract response text from LLM
        response_text = response.choices[0].message.content
        logger.debug(f"LLM response (attempt 1): {response_text[:200]}...")
        
        # Try to parse response into clips
        try:
            clips = parse_llm_response(response_text)
            logger.info(f"First LLM call succeeded: {len(clips)} clips extracted")
            return clips
            
        except ValueError as parse_error:
            # First parse failed, log warning and proceed to retry
            logger.warning(
                f"First parse attempt failed: {str(parse_error)}. "
                "Retrying with stricter prompt..."
            )
            
            # ─── SECOND LLM CALL ATTEMPT (with stricter instructions) ───
            # Create stricter system prompt that emphasizes JSON-only output
            stricter_system = (
                system_prompt 
                + "\n\nIMPORTANT: Return ONLY raw JSON array. No text before or after. "
                + "No markdown. No explanation. ONLY JSON."
            )
            
            logger.debug("Calling Groq LLM for clip analysis (attempt 2/2, stricter)...")
            response2 = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                max_tokens=1000,
                messages=[
                    {"role": "system", "content": stricter_system},
                    {"role": "user", "content": user_message},
                ],
            )
            
            # Extract response text from second attempt
            response_text2 = response2.choices[0].message.content
            logger.debug(f"LLM response (attempt 2): {response_text2[:200]}...")
            
            # Try to parse second response
            try:
                clips = parse_llm_response(response_text2)
                logger.info(f"Second LLM call succeeded: {len(clips)} clips extracted")
                return clips
                
            except ValueError as parse_error2:
                # Both attempts failed - give up and raise error
                error_msg = (
                    f"Transcript analysis failed after 2 attempts. "
                    f"Final error: {str(parse_error2)}"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg) from parse_error2
        
    except RuntimeError as e:
        # Re-raise RuntimeErrors as-is
        raise
        
    except Exception as e:
        # Catch any other unexpected errors from LLM API or elsewhere
        error_msg = f"Unexpected error during transcript analysis: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


if __name__ == "__main__":
    print("analyzer.py loaded successfully")
