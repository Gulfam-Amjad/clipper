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


def parse_llm_response(response_text: str) -> tuple[list[dict], str]:
    """
    Parses and validates LLM response as a JSON object containing clips.
    
    Removes markdown code fences if present, validates JSON structure,
    ensures all clips have required fields with correct types and values.
    
    Args:
        response_text: Raw text response from LLM
        
    Returns:
        Tuple of (clips list, music style string)
        
    Raises:
        ValueError: If parsing fails or any validation check fails
    """
    allowed_music_styles = {"phonk", "lofi", "epic", "chill", "upbeat"}

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
        result = json.loads(cleaned)
        
        # Validate that result is an object with clips and music_style keys
        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object, got: " + str(type(result)))

        if "clips" not in result:
            raise ValueError("LLM response missing required 'clips' field")

        clips = result["clips"]
        music_style = result.get("music_style", "lofi")

        if not isinstance(music_style, str) or music_style not in allowed_music_styles:
            music_style = "lofi"

        # Validate that clips is a list
        if not isinstance(clips, list):
            raise ValueError("LLM response 'clips' must be a JSON array, got: " + str(type(clips)))
        
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
            
            # Allow equal timestamps here so the repair step can expand zero-length
            # LLM outputs into valid clip windows before strict validation runs.
            if clip["start"] > clip["end"]:
                raise ValueError(
                    f"Clip {i} has invalid time range: start ({clip['start']}) > end ({clip['end']})"
                )
        
        # Parsing succeeded; strict clip bounds are enforced after repair.
        logger.info(f"Successfully parsed {len(clips)} clips from LLM response")
        return clips, music_style
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in LLM response: {str(e)}") from e
    except ValueError as e:
        raise


def _repair_analyzed_clips(clips: list[dict], segments: list[dict]) -> list[dict]:
    """
    Repairs LLM-produced clip bounds so they satisfy the downstream validator.

    The LLM can occasionally return very short or zero-length ranges even when the
    prompt asks for 30-180 second clips. This helper expands those clips to a valid
    window while preserving their ordering and avoiding overlap.
    """
    if not segments:
        raise ValueError("No transcript segments available to repair clips")

    transcript_end = max(float(segment["end"]) for segment in segments)
    repaired_clips: list[dict] = []

    for index, clip in enumerate(sorted(clips, key=lambda item: float(item["start"]))):
        start = float(clip["start"])
        end = float(clip["end"])
        label = str(clip["label"])

        if repaired_clips and start < repaired_clips[-1]["end"]:
            start = repaired_clips[-1]["end"]

        if end <= start:
            end = start + 30.0

        duration = end - start
        if duration < 30.0:
            end = start + 30.0
        elif duration > 180.0:
            end = start + 180.0

        if end > transcript_end:
            end = transcript_end
            start = max(0.0, end - 30.0)

        if repaired_clips and start < repaired_clips[-1]["end"]:
            start = repaired_clips[-1]["end"]

        if end <= start or end - start < 30.0:
            raise ValueError(
                f"Clip {index} could not be repaired into a valid 30-180s range"
            )

        repaired_clips.append({"start": start, "end": end, "label": label})

    return validate_clip_bounds(repaired_clips)


def analyze_transcript(segments: list[dict], guidance: str = None) -> tuple[list[dict], str]:
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
        Tuple of (clips list, music style string)
        
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
- Return ONLY a valid JSON object. No explanation. No markdown. No extra text.
- Timestamps must be in seconds as floats (e.g. 45.0, not "0:45")

Also select the most fitting background music style for this video content.
Choose ONE from: phonk, lofi, epic, chill, upbeat
Base your choice on the video's energy and topic:
- phonk: high-energy, intense, action content
- lofi: calm study, educational, slow-paced explanations
- epic: motivational, achievement, big announcements
- chill: lifestyle, casual, conversational
- upbeat: product demos, tutorials, tech content
Return the result as a JSON object with 'music_style' and 'clips' keys.

Output format (return ONLY this JSON, nothing else):
{
    "music_style": "phonk",
    "clips": [
        {"start": 45.2, "end": 98.7, "label": "Main concept explained"},
        {"start": 134.0, "end": 187.3, "label": "Key example given"}
    ]
}"""
        
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
            clips, music_style = parse_llm_response(response_text)
            clips = _repair_analyzed_clips(clips, segments)
            logger.info(f"First LLM call succeeded: {len(clips)} clips extracted")
            return clips, music_style
            
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
                + "\n\nIMPORTANT: Return ONLY raw JSON object. No text before or after. "
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
                clips, music_style = parse_llm_response(response_text2)
                clips = _repair_analyzed_clips(clips, segments)
                logger.info(f"Second LLM call succeeded: {len(clips)} clips extracted")
                return clips, music_style
                
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


def score_clips(clips: list[dict], all_segments: list[dict]) -> list[dict]:
    """
    Adds a heuristic quality score to each clip based on transcript content.

    The score is computed locally without any API calls and is clamped to the
    0-100 range.
    """
    signals = [
        "important",
        "key",
        "main",
        "because",
        "result",
        "conclusion",
        "example",
        "first",
        "finally",
        "therefore",
        "means",
        "shows",
        "proves",
        "actually",
        "critical",
        "essential",
        "significant",
    ]
    questions = ["what", "why", "how", "when", "which"]
    fillers = ["um", "uh", "like", "you know", "basically", "literally"]

    for clip in clips:
        overlap_segments = [
            segment
            for segment in all_segments
            if segment["start"] < clip["end"] and segment["end"] > clip["start"]
        ]
        clip_text = " ".join(segment["text"] for segment in overlap_segments).lower()

        score = 50
        word_count = len(clip_text.split())

        if word_count > 80:
            score += 10
        elif word_count > 40:
            score += 5
        if word_count < 15:
            score -= 10

        signal_score = 0
        for signal in signals:
            signal_score += clip_text.count(signal) * 3
        score += min(20, signal_score)

        question_score = 0
        for question in questions:
            question_score += clip_text.count(question) * 2
        score += min(10, question_score)

        for filler in fillers:
            score -= clip_text.count(filler) * 2

        clip_duration = clip["end"] - clip["start"]
        if 60 <= clip_duration <= 120:
            score += 10
        elif 30 <= clip_duration < 60:
            score += 5
        elif clip_duration > 180:
            score -= 5

        clip["quality_score"] = int(min(100, max(0, score)))

    return clips


if __name__ == "__main__":
    print("analyzer.py loaded successfully")
