"""Chapter detection service for VideoClipper.

This module analyzes transcript segments and generates YouTube chapter points
using Groq when available, with a safe fallback when the model cannot be used.
"""

import json
import logging
import os
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        """Fallback no-op loader when python-dotenv is unavailable."""
        return False

try:
    from groq import Groq
except Exception:
    Groq = None  # type: ignore[assignment]


# Load environment variables at import time.
load_dotenv()


# Configure module logging and lazy Groq client caching.
logger = logging.getLogger(__name__)
_groq_client: Groq | None = None


def _safe_str(value: Any) -> str:
    """Convert any value to a trimmed string without raising."""
    try:
        if value is None:
            return ""
        return str(value).strip()
    except Exception:
        logger.exception("Failed to convert value to string")
        return ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert any value to float with a safe default."""
    try:
        return float(value)
    except Exception:
        return default


def _seconds_to_mmss(seconds: float) -> str:
    """Format seconds as M:SS for YouTube chapter text."""
    try:
        total_seconds = max(0, int(seconds))
        minutes = total_seconds // 60
        remaining_seconds = total_seconds % 60
        return f"{minutes}:{remaining_seconds:02d}"
    except Exception:
        logger.exception("Failed to format chapter timestamp")
        return "0:00"


def _get_groq_client() -> Groq | None:
    """Lazy-load and cache the Groq client."""
    try:
        global _groq_client

        # Reuse the cached client when available.
        if _groq_client is not None:
            return _groq_client

        # Read the API key from the environment.
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.error("GROQ_API_KEY is not set")
            return None

        # Respect environments that do not have the Groq SDK installed.
        if Groq is None:
            logger.error("Groq SDK is not available in this environment")
            return None

        # Create the client only when chapter detection is requested.
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq client initialized for chapter detection")
        return _groq_client
    except Exception:
        logger.exception("Failed to initialize Groq client")
        return None


def _fallback_chapters() -> list[dict]:
    """Return the documented fallback chapter structure."""
    try:
        return [
            {
                "timestamp": 0.0,
                "timestamp_str": "0:00",
                "title": "Full Video",
            }
        ]
    except Exception:
        logger.exception("Failed to build fallback chapters")
        return [{"timestamp": 0.0, "timestamp_str": "0:00", "title": "Full Video"}]


def _format_transcript(segments: list[dict]) -> str:
    """Format transcript segments for LLM analysis."""
    try:
        # Build a readable transcript with timestamps in brackets.
        lines: list[str] = []
        for segment in segments:
            try:
                timestamp = _safe_float(segment.get("start", 0.0), 0.0)
                text = _safe_str(segment.get("text", ""))
                if text:
                    lines.append(f"[{_seconds_to_mmss(timestamp)}] {text}")
            except Exception:
                logger.exception("Failed to format a transcript segment; skipping it")

        return "\n".join(lines)
    except Exception:
        logger.exception("Failed to format transcript for chapter detection")
        return ""


def _extract_json_array(response_text: str) -> list[Any] | None:
    """Extract and parse a JSON array from an LLM response."""
    try:
        # Remove surrounding whitespace and markdown fences.
        cleaned = _safe_str(response_text)
        if not cleaned:
            return None

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 2:
                cleaned = "\n".join(lines[1:])
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        # Trim to the outermost JSON array boundaries.
        start_index = cleaned.find("[")
        end_index = cleaned.rfind("]")
        if start_index == -1 or end_index == -1 or end_index <= start_index:
            return None

        payload = cleaned[start_index : end_index + 1]
        parsed = json.loads(payload)
        if not isinstance(parsed, list):
            return None

        return parsed
    except Exception:
        logger.exception("Failed to parse JSON array from chapter response")
        return None


def _normalize_chapters(chapters: list[Any], video_duration: float) -> list[dict]:
    """Validate, sort, and normalize chapter timestamps and titles."""
    try:
        # Convert each entry to a predictable chapter dict.
        normalized: list[dict] = []
        for item in chapters:
            try:
                if not isinstance(item, dict):
                    continue

                timestamp = _safe_float(item.get("timestamp", 0.0), 0.0)
                title = _safe_str(item.get("title", "")).strip()
                if not title:
                    continue

                # Clamp timestamps into the video duration range.
                if video_duration > 0:
                    timestamp = max(0.0, min(timestamp, float(video_duration)))
                else:
                    timestamp = max(0.0, timestamp)

                # Enforce a reasonable title length for YouTube chapters.
                title = title[:40].strip()
                if not title:
                    continue

                normalized.append({"timestamp": float(timestamp), "title": title})
            except Exception:
                logger.exception("Failed to normalize a chapter entry; skipping it")

        # Sort chapters by timestamp and remove non-ascending duplicates.
        normalized.sort(key=lambda chapter: chapter["timestamp"])
        deduped: list[dict] = []
        for chapter in normalized:
            if not deduped:
                deduped.append(chapter)
                continue
            if chapter["timestamp"] >= deduped[-1]["timestamp"]:
                deduped.append(chapter)

        # Ensure the first chapter starts at 0.0.
        if not deduped:
            return _fallback_chapters()

        if deduped[0]["timestamp"] != 0.0:
            first_title = deduped[0].get("title", "Introduction") or "Introduction"
            deduped.insert(0, {"timestamp": 0.0, "title": first_title[:40].strip() or "Introduction"})

        # Enforce at least 30 seconds spacing by dropping too-close chapters.
        spaced: list[dict] = []
        for chapter in deduped:
            if not spaced:
                spaced.append(chapter)
                continue
            if chapter["timestamp"] - spaced[-1]["timestamp"] >= 30.0:
                spaced.append(chapter)

        # Add timestamp_str for every chapter.
        for chapter in spaced:
            chapter["timestamp_str"] = _seconds_to_mmss(chapter["timestamp"])

        return spaced if spaced else _fallback_chapters()
    except Exception:
        logger.exception("Failed to normalize chapter list")
        return _fallback_chapters()


def detect_chapters(segments: list[dict], video_duration: float) -> list[dict]:
    """Detect natural topic changes and generate YouTube chapter timestamps."""
    try:
        # Validate the input segments before any processing.
        if not isinstance(segments, list) or not segments:
            logger.warning("No transcript segments provided for chapter detection")
            return _fallback_chapters()

        # Format the transcript into the structure expected by the LLM.
        formatted_transcript = _format_transcript(segments)
        if not formatted_transcript:
            logger.warning("Formatted transcript was empty; using fallback chapters")
            return _fallback_chapters()

        # Load the Groq client and fall back if unavailable.
        client = _get_groq_client()
        if client is None:
            logger.warning("Groq client unavailable; using fallback chapters")
            return _fallback_chapters()

        # Compose the exact system prompt requested by the task.
        system_prompt = (
            "You are a YouTube chapter creator. Identify natural topic transitions "
            "in video transcripts. Return ONLY valid JSON array."
        )

        # Compose the exact user prompt requested by the task.
        user_prompt = (
            "Identify 4-8 chapter points in this video transcript.\n"
            f"Video duration: {float(video_duration):.0f} seconds\n\n"
            "Transcript:\n"
            f"{formatted_transcript[:2000]}\n\n"
            "Rules:\n"
            "- First chapter must start at 0\n"
            "- Space chapters at least 30 seconds apart\n"
            "- Titles max 40 characters, descriptive\n"
            "- Timestamps in seconds as floats\n\n"
            "Return ONLY JSON array:\n"
            "[{\'timestamp\': 0.0, \'title\': \'Introduction\'}, ...]"
        )

        # Call the LLM for chapter detection.
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        # Extract the first response choice and parse it.
        response_text = ""
        if response and getattr(response, "choices", None):
            first_choice = response.choices[0]
            response_text = _safe_str(getattr(getattr(first_choice, "message", None), "content", ""))

        # Normalize the parsed chapters and return them when valid.
        parsed = _extract_json_array(response_text)
        if not isinstance(parsed, list):
            logger.warning("Chapter detection response was invalid JSON; using fallback")
            return _fallback_chapters()

        normalized = _normalize_chapters(parsed, _safe_float(video_duration, 0.0))
        if not normalized:
            logger.warning("Normalized chapter list was empty; using fallback")
            return _fallback_chapters()

        return normalized
    except Exception:
        logger.exception("Error detecting chapters; using fallback")
        return _fallback_chapters()


def format_chapters_for_youtube(chapters: list[dict]) -> str:
    """Convert chapter dicts into YouTube description format."""
    try:
        # Validate the input structure and normalize before formatting.
        if not isinstance(chapters, list) or not chapters:
            logger.warning("No chapters provided to format for YouTube")
            return ""

        lines: list[str] = []
        for chapter in chapters:
            try:
                if not isinstance(chapter, dict):
                    continue

                timestamp = chapter.get("timestamp")
                title = _safe_str(chapter.get("title", "")).strip()
                if not title:
                    continue

                timestamp_str = _safe_str(chapter.get("timestamp_str", "")).strip()
                if not timestamp_str:
                    timestamp_str = _seconds_to_mmss(_safe_float(timestamp, 0.0))

                lines.append(f"{timestamp_str} {title}")
            except Exception:
                logger.exception("Failed to format a chapter line; skipping it")

        return "\n".join(lines)
    except Exception:
        logger.exception("Error formatting chapters for YouTube")
        return ""


# Allow direct execution for a quick import sanity check.
if __name__ == "__main__":
    print("chapter_detector.py loaded OK")