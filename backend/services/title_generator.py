"""Title and metadata generation service for VideoClipper.

This module uses Groq Llama 3.3 70B to generate YouTube-optimized metadata
for each clip after the clip boundaries have already been selected.
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


# Load environment variables as soon as the module is imported.
load_dotenv()


# Configure module-level logging and cache the Groq client lazily.
logger = logging.getLogger(__name__)
_groq_client: Groq | None = None


def _safe_str(value: Any) -> str:
    """Convert any value to a trimmed string."""
    try:
        if value is None:
            return ""
        return str(value).strip()
    except Exception:
        logger.exception("Failed to convert value to string")
        return ""


def _build_default_hashtags(label: str) -> list[str]:
    """Build a small fallback hashtag list from the clip label."""
    try:
        # Start with label-derived words so the fallback stays relevant.
        words: list[str] = []
        for raw_word in label.replace("/", " ").replace("-", " ").split():
            cleaned = "".join(character for character in raw_word if character.isalnum())
            if cleaned:
                words.append(cleaned)

        # Add broad YouTube-friendly defaults when the label is sparse.
        defaults = ["Shorts", "Clip", "Highlights", "YouTube", "Video"]

        # Remove duplicates while preserving order.
        hashtags: list[str] = []
        for candidate in words + defaults:
            if candidate and candidate not in hashtags:
                hashtags.append(candidate)

        return hashtags[:7] if hashtags else defaults
    except Exception:
        logger.exception("Failed to build default hashtags")
        return ["Shorts", "Clip", "Highlights", "YouTube", "Video"]


def _fallback_metadata(clip: dict) -> dict:
    """Return safe fallback metadata when the LLM response cannot be used."""
    try:
        # Use the clip label as the title whenever possible.
        label = _safe_str(clip.get("label", "")) or "Untitled Clip"

        # Create a simple human-readable description for the fallback path.
        description = f"{label}. Watch the full clip for the key moment and context."

        # Keep the fallback hook short and viewer-friendly.
        hook_words = label.split()
        hook = " ".join(hook_words[:15]) if hook_words else "Watch the key moment unfold."

        # Generate relevant default hashtags from the clip label.
        hashtags = _build_default_hashtags(label)

        return {
            "title": label[:70],
            "description": description,
            "hashtags": hashtags,
            "hook": hook[:120],
        }
    except Exception:
        logger.exception("Failed to build fallback metadata")
        return {
            "title": "Untitled Clip",
            "description": "Watch this clip for the key moment and context.",
            "hashtags": ["Shorts", "Clip", "Highlights", "YouTube", "Video"],
            "hook": "Watch the key moment unfold.",
        }


def _get_groq_client() -> Groq | None:
    """Lazy-load and cache the Groq client."""
    try:
        global _groq_client

        # Reuse the existing client if one was already created.
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

        # Create the client only when metadata generation is needed.
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq client initialized for title generation")
        return _groq_client
    except Exception:
        logger.exception("Failed to initialize Groq client")
        return None


def _extract_json_payload(response_text: str) -> dict[str, Any] | None:
    """Extract and parse a JSON object from the model response."""
    try:
        # Remove surrounding whitespace and markdown code fences.
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

        # Trim any explanatory text around the JSON object.
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
        logger.exception("Failed to extract JSON payload from model response")
        return None


def _normalize_metadata(metadata: dict[str, Any] | None, clip: dict) -> dict:
    """Validate and normalize the metadata shape required by the caller."""
    try:
        # Prepare a safe fallback first so every failure path returns valid data.
        fallback = _fallback_metadata(clip)
        if not isinstance(metadata, dict):
            logger.warning("Metadata payload was not a dictionary; using fallback")
            return fallback

        # Validate the required keys before accepting the response.
        required_keys = ["title", "description", "hashtags", "hook"]
        for key in required_keys:
            if key not in metadata:
                logger.warning("Metadata response missing key '%s'; using fallback", key)
                return fallback

        # Normalize the title and clamp it to the requested length.
        title = _safe_str(metadata.get("title")) or fallback["title"]
        title = title[:70].strip()
        if not title:
            title = fallback["title"]

        # Normalize the description while preserving natural language text.
        description = _safe_str(metadata.get("description")) or fallback["description"]

        # Normalize hashtags into a compact list without the # symbol.
        raw_hashtags = metadata.get("hashtags")
        hashtags: list[str] = []
        if isinstance(raw_hashtags, list):
            for tag in raw_hashtags:
                cleaned_tag = _safe_str(tag).lstrip("#").strip()
                if cleaned_tag and cleaned_tag not in hashtags:
                    hashtags.append(cleaned_tag)

        # Fill missing hashtag slots with label-derived defaults.
        if len(hashtags) < 5:
            fallback_tags = _build_default_hashtags(_safe_str(clip.get("label", "")))
            for tag in fallback_tags:
                cleaned_tag = _safe_str(tag).lstrip("#").strip()
                if cleaned_tag and cleaned_tag not in hashtags:
                    hashtags.append(cleaned_tag)
                if len(hashtags) >= 5:
                    break

        hashtags = hashtags[:7] if hashtags else fallback["hashtags"]

        # Normalize the hook and enforce the requested word limit.
        hook = _safe_str(metadata.get("hook")) or fallback["hook"]
        hook_words = hook.split()
        hook = " ".join(hook_words[:15]).strip()
        if not hook:
            hook = fallback["hook"]

        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "hook": hook,
        }
    except Exception:
        logger.exception("Failed to normalize metadata; using fallback")
        return _fallback_metadata(clip)


def generate_clip_metadata(clip: dict, transcript_text: str) -> dict:
    """Generate YouTube-optimized metadata for a single clip."""
    try:
        # Build a safe fallback up front so every failure path returns a result.
        safe_clip = clip if isinstance(clip, dict) else {"label": _safe_str(clip)}
        fallback = _fallback_metadata(safe_clip)

        # Extract and sanitize the clip fields needed for the prompt.
        label = _safe_str(safe_clip.get("label", "")) or "Untitled Clip"
        duration = safe_clip.get("duration", 0)
        try:
            duration_value = float(duration)
        except Exception:
            duration_value = 0.0

        # Load the Groq client before making the request.
        client = _get_groq_client()
        if client is None:
            logger.warning("Groq client unavailable; using fallback metadata")
            return fallback

        # Compose the system prompt exactly as requested.
        system_prompt = (
            "You are a YouTube content strategist. Generate metadata for video clips. "
            "Always return ONLY valid JSON, no markdown, no explanation."
        )

        # Compose the user prompt with a transcript preview for the model.
        user_prompt = (
            "Generate YouTube metadata for this video clip.\n"
            f"Clip label: {label}\n"
            f"Duration: {duration_value:.0f} seconds\n"
            f"Transcript: {_safe_str(transcript_text)[:500]}\n\n"
            "Return ONLY this JSON:\n"
            "{\n"
            "  'title': 'engaging title max 70 chars',\n"
            "  'description': '2-3 sentence description',\n"
            "  'hashtags': ['tag1', 'tag2', 'tag3', 'tag4', 'tag5'],\n"
            "  'hook': 'opening hook sentence max 15 words'\n"
            "}"
        )

        # Ask Groq for the metadata using the required model and parameters.
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        # Read the first response choice and parse it as JSON.
        response_text = ""
        if response and getattr(response, "choices", None):
            first_choice = response.choices[0]
            response_text = _safe_str(getattr(getattr(first_choice, "message", None), "content", ""))

        # Normalize the parsed response and fall back if anything is missing.
        parsed_metadata = _extract_json_payload(response_text)
        normalized_metadata = _normalize_metadata(parsed_metadata, safe_clip)
        if normalized_metadata == fallback:
            logger.warning("Using fallback metadata for clip '%s'", label)
        else:
            logger.info("Generated metadata for clip '%s'", label)

        return normalized_metadata
    except Exception:
        logger.exception("Error generating clip metadata; using fallback")
        safe_clip = clip if isinstance(clip, dict) else {"label": _safe_str(clip)}
        return _fallback_metadata(safe_clip)


def generate_all_metadata(clips: list[dict], segments: list[dict]) -> list[dict]:
    """Generate metadata for every clip sequentially and merge it into each clip."""
    try:
        # Validate the incoming collections and keep the function resilient.
        if not isinstance(clips, list):
            logger.warning("Clips input was not a list; returning an empty list")
            return []
        if not isinstance(segments, list):
            logger.warning("Segments input was not a list; using an empty segment set")
            segments = []

        # Process each clip one at a time to avoid Groq rate limits.
        updated_clips: list[dict] = []
        total = len(clips)
        for index, clip in enumerate(clips, start=1):
            try:
                # Log progress so callers can track long-running jobs.
                logger.info("Generating metadata for clip %s of %s", index, total)

                # Pull the clip boundaries used to collect overlapping transcript text.
                clip_start = float(clip.get("start", 0))
                clip_end = float(clip.get("end", 0))

                # Gather only transcript segments that overlap this clip window.
                overlapping_segments = []
                for segment in segments:
                    try:
                        seg_start = float(segment.get("start", 0))
                        seg_end = float(segment.get("end", 0))
                        if seg_start < clip_end and seg_end > clip_start:
                            overlapping_segments.append(segment)
                    except Exception:
                        logger.exception("Failed to inspect a transcript segment; skipping it")

                # Join all overlapping transcript text into a single prompt string.
                transcript_text = " ".join(
                    _safe_str(segment.get("text", ""))
                    for segment in overlapping_segments
                    if _safe_str(segment.get("text", ""))
                ).strip()

                # Generate and attach the metadata directly onto the clip dictionary.
                metadata = generate_clip_metadata(clip, transcript_text)
                if isinstance(clip, dict):
                    clip.update(metadata)
                    updated_clips.append(clip)
                else:
                    updated_clips.append({"clip": clip, **metadata})
            except Exception:
                logger.exception("Failed to generate metadata for clip %s; using fallback", index)
                if isinstance(clip, dict):
                    clip.update(_fallback_metadata(clip))
                    updated_clips.append(clip)
                else:
                    updated_clips.append({"label": _safe_str(clip), **_fallback_metadata({"label": _safe_str(clip)})})

        # Return the enriched clips in the same order they were received.
        return updated_clips
    except Exception:
        logger.exception("Unexpected error generating metadata for all clips")
        return clips if isinstance(clips, list) else []


# Test module import path manually when run as a script.
if __name__ == "__main__":
    logger.info("title_generator.py loaded OK")