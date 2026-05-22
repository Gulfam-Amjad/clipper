"""Viral scoring service for VideoClipper.

This module provides a fast heuristic scorer and an optional Groq-powered LLM
scorer to estimate how likely a clip is to perform well on short-form social
video platforms.
"""

import json
import logging
import os
import re
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


# Load environment variables at import time so GROQ_API_KEY is available early.
load_dotenv()


# Set up module-level logging and cache the Groq client lazily.
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


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert any value to int with a safe default."""
    try:
        return int(float(value))
    except Exception:
        return default


def _fallback_llm_score() -> dict:
    """Return the documented fallback structure for LLM scoring."""
    return {
        "viral_score": 50,
        "platform_fit": {},
        "best_hook": "",
        "improvement": "",
    }


def _get_groq_client() -> Groq | None:
    """Lazy-load and cache the Groq client."""
    try:
        global _groq_client

        # Reuse the existing client if one has already been created.
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

        # Create the client only when the LLM scorer is actually used.
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq client initialized for viral scoring")
        return _groq_client
    except Exception:
        logger.exception("Failed to initialize Groq client")
        return None


def _extract_json_payload(response_text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a model response."""
    try:
        # Remove whitespace and optional markdown code fences.
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

        # Trim everything outside the first JSON object.
        start_index = cleaned.find("{")
        end_index = cleaned.rfind("}")
        if start_index == -1 or end_index == -1 or end_index <= start_index:
            return None

        payload = cleaned[start_index : end_index + 1]
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            return None

        return parsed
    except Exception:
        logger.exception("Failed to parse JSON payload from LLM response")
        return None


def _normalize_heuristic_result(score: int, reasons: list[str], warnings: list[str]) -> dict:
    """Clamp the heuristic score and return the required response shape."""
    try:
        # Clamp the score into the required range.
        normalized_score = min(100, max(0, _safe_int(score, 0)))

        # Make sure both lists contain only strings.
        normalized_reasons = [item for item in (_safe_str(reason) for reason in reasons) if item]
        normalized_warnings = [item for item in (_safe_str(warning) for warning in warnings) if item]

        return {
            "score": normalized_score,
            "reasons": normalized_reasons,
            "warnings": normalized_warnings,
        }
    except Exception:
        logger.exception("Failed to normalize heuristic score")
        return {"score": 50, "reasons": [], "warnings": []}


def heuristic_viral_score(clip: dict, transcript_text: str) -> dict:
    """Score a clip's viral potential using local heuristics only."""
    try:
        # Prepare safe clip fields and transcript text.
        safe_clip = clip if isinstance(clip, dict) else {}
        label = _safe_str(safe_clip.get("label", "Untitled Clip")) or "Untitled Clip"
        duration = _safe_float(safe_clip.get("duration", 0.0), 0.0)
        transcript = _safe_str(transcript_text)
        transcript_lower = transcript.lower()

        # Start at the requested baseline.
        score = 50
        reasons: list[str] = []
        warnings: list[str] = []

        # Positive duration signals.
        if 45 <= duration <= 90:
            score += 15
            reasons.append("Ideal duration for Shorts")
        elif 30 <= duration <= 120:
            score += 10
            reasons.append("Good duration range for short-form video")

        # Positive language signals.
        question_words = ["what", "why", "how", "secret", "truth"]
        if any(word in transcript_lower for word in question_words):
            score += 8
            reasons.append("Contains curiosity-driven language")

        power_words = ["never", "always", "best", "worst", "only"]
        if any(word in transcript_lower for word in power_words):
            score += 8
            reasons.append("Contains strong power words")

        emotion_words = ["amazing", "shocking", "unbelievable", "incredible"]
        if any(word in transcript_lower for word in emotion_words):
            score += 6
            reasons.append("Strong emotional wording detected")

        # Speech density and structure signals.
        word_count = len(transcript.split())
        if 80 <= word_count <= 200:
            score += 5
            reasons.append("Good speech density for a clip")

        if re.search(r"\d+%", transcript):
            score += 5
            reasons.append("Includes numbers or statistics")

        list_indicators = ["first", "second", "third", "number"]
        if any(indicator in transcript_lower for indicator in list_indicators):
            score += 4
            reasons.append("Uses list-style structure")

        # Negative duration signals.
        if duration > 180:
            score -= 10
            warnings.append("Clip is longer than 3 minutes")

        if duration < 20:
            score -= 5
            warnings.append("Clip is too short to hold attention")

        # Negative sparsity signal.
        if word_count < 20:
            score -= 8
            warnings.append("Transcript is too sparse")

        # Filler word penalty capped at -15.
        filler_words = ["um", "uh", "like", "basically"]
        filler_hits = 0
        for filler in filler_words:
            filler_hits += len(re.findall(rf"\b{re.escape(filler)}\b", transcript_lower))

        if filler_hits > 0:
            filler_penalty = min(15, filler_hits * 5)
            score -= filler_penalty
            warnings.append(f"Too many filler words detected ({filler_hits} found)")

        # Add a label-based reason when available, without affecting the score.
        if label and label != "Untitled Clip":
            reasons.append(f"Analyzed clip: {label}")

        # Return the normalized structure.
        return _normalize_heuristic_result(score, reasons, warnings)
    except Exception:
        logger.exception("Error computing heuristic viral score")
        return {"score": 50, "reasons": [], "warnings": []}


def llm_viral_score(clip: dict, transcript_text: str) -> dict:
    """Ask Groq to analyze viral potential for a clip."""
    try:
        # Build a safe fallback result in case anything fails.
        fallback = _fallback_llm_score()

        # Extract and sanitize the clip fields needed by the prompt.
        safe_clip = clip if isinstance(clip, dict) else {}
        label = _safe_str(safe_clip.get("label", "Untitled Clip")) or "Untitled Clip"
        duration = _safe_float(safe_clip.get("duration", 0.0), 0.0)
        transcript = _safe_str(transcript_text)[:400]

        # Load the Groq client and fall back if it is not available.
        client = _get_groq_client()
        if client is None:
            logger.warning("Groq client unavailable; using fallback LLM viral score")
            return fallback

        # Compose the system prompt exactly as requested.
        system_prompt = (
            "You are a viral content expert. Analyze video clips for viral potential. "
            "Return ONLY valid JSON."
        )

        # Compose the user prompt with the required output schema.
        user_prompt = (
            "Rate this video clip's viral potential for YouTube Shorts/TikTok.\n"
            f"Label: {label}\n"
            f"Duration: {duration:.0f}s\n"
            f"Transcript: {transcript}\n\n"
            "Return ONLY:\n"
            "{\n"
            "  'viral_score': 75,\n"
            "  'platform_fit': {'youtube_shorts': 80, 'tiktok': 70, 'instagram': 65},\n"
            "  'best_hook': 'suggested opening line',\n"
            "  'improvement': 'one specific suggestion to make it more viral'\n"
            "}"
        )

        # Ask Groq for the viral analysis using the required model settings.
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.4,
            max_tokens=400,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        # Extract the first response payload safely.
        response_text = ""
        if response and getattr(response, "choices", None):
            first_choice = response.choices[0]
            response_text = _safe_str(getattr(getattr(first_choice, "message", None), "content", ""))

        # Parse and validate the expected schema.
        parsed = _extract_json_payload(response_text)
        if not isinstance(parsed, dict):
            logger.warning("LLM viral score response was not valid JSON; using fallback")
            return fallback

        # Validate the required keys before accepting the response.
        required_keys = ["viral_score", "platform_fit", "best_hook", "improvement"]
        for key in required_keys:
            if key not in parsed:
                logger.warning("LLM viral score missing key '%s'; using fallback", key)
                return fallback

        # Normalize all fields into the required output format.
        viral_score = min(100, max(0, _safe_int(parsed.get("viral_score", 50), 50)))
        platform_fit_raw = parsed.get("platform_fit", {})
        platform_fit: dict[str, int] = {}
        if isinstance(platform_fit_raw, dict):
            for key, value in platform_fit_raw.items():
                platform_fit[_safe_str(key)] = min(100, max(0, _safe_int(value, 0)))

        best_hook = _safe_str(parsed.get("best_hook", ""))
        improvement = _safe_str(parsed.get("improvement", ""))

        return {
            "viral_score": viral_score,
            "platform_fit": platform_fit,
            "best_hook": best_hook,
            "improvement": improvement,
        }
    except Exception:
        logger.exception("Error generating LLM viral score; using fallback")
        return _fallback_llm_score()


def score_all_clips(clips: list[dict], segments: list[dict], use_llm: bool = True) -> list[dict]:
    """Score each clip sequentially and add heuristic, LLM, and combined scores."""
    try:
        # Validate inputs and keep the function safe on malformed data.
        if not isinstance(clips, list):
            logger.warning("Clips input was not a list; returning an empty list")
            return []
        if not isinstance(segments, list):
            logger.warning("Segments input was not a list; using an empty segment set")
            segments = []

        # Process clips one at a time to keep the workflow predictable and robust.
        updated_clips: list[dict] = []
        top_score = 0

        for clip in clips:
            try:
                # Pull clip boundaries for transcript overlap detection.
                safe_clip = clip if isinstance(clip, dict) else {"label": _safe_str(clip)}
                clip_start = _safe_float(safe_clip.get("start", 0.0), 0.0)
                clip_end = _safe_float(safe_clip.get("end", 0.0), 0.0)

                # Collect the transcript text from all overlapping segments.
                overlapping_text_parts: list[str] = []
                for segment in segments:
                    try:
                        seg_start = _safe_float(segment.get("start", 0.0), 0.0)
                        seg_end = _safe_float(segment.get("end", 0.0), 0.0)
                        if seg_start < clip_end and seg_end > clip_start:
                            text = _safe_str(segment.get("text", ""))
                            if text:
                                overlapping_text_parts.append(text)
                    except Exception:
                        logger.exception("Failed to inspect a transcript segment; skipping it")

                # Join the transcript into a single string for scoring.
                transcript_text = " ".join(overlapping_text_parts).strip()

                # Always compute the heuristic score.
                heuristic_result = heuristic_viral_score(safe_clip, transcript_text)
                safe_clip["viral_heuristic"] = heuristic_result

                # Optionally compute the LLM-enhanced score.
                llm_result = _fallback_llm_score()
                llm_failed = True
                if use_llm:
                    llm_result = llm_viral_score(safe_clip, transcript_text)
                    llm_failed = llm_result == _fallback_llm_score()
                    safe_clip["viral_llm"] = llm_result

                # Combine the scores using the requested weighting.
                heuristic_score = _safe_int(heuristic_result.get("score", 50), 50)
                if use_llm and not llm_failed:
                    llm_score = _safe_int(llm_result.get("viral_score", 50), 50)
                    combined_score = int((heuristic_score * 0.4) + (llm_score * 0.6))
                else:
                    combined_score = heuristic_score

                safe_clip["combined_viral_score"] = min(100, max(0, int(combined_score)))
                updated_clips.append(safe_clip)
                top_score = max(top_score, safe_clip["combined_viral_score"])
            except Exception:
                logger.exception("Failed to score a clip; using fallback values")
                fallback_clip = clip if isinstance(clip, dict) else {"label": _safe_str(clip)}
                fallback_clip["viral_heuristic"] = {"score": 50, "reasons": [], "warnings": []}
                if use_llm:
                    fallback_clip["viral_llm"] = _fallback_llm_score()
                fallback_clip["combined_viral_score"] = 50
                updated_clips.append(fallback_clip)
                top_score = max(top_score, 50)

        # Log the final top score for observability.
        logger.info("Viral scoring complete. Top clip score: %s", top_score)
        return updated_clips
    except Exception:
        logger.exception("Unexpected error while scoring all clips")
        return clips if isinstance(clips, list) else []


# Allow direct execution for a quick import sanity check.
if __name__ == "__main__":
    print("viral_scorer.py loaded OK")