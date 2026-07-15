import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

try:
    import google.generativeai as genai
except ImportError:  # Gemini fallback is optional.
    genai = None

load_dotenv()

BUFFER_SECONDS = 1.5
DEFAULT_MIN_LENGTH = 20.0
DEFAULT_MAX_LENGTH = 150.0


def _build_transcript_prompt(transcript_data: dict) -> str:
    segments = transcript_data.get("segments", [])
    if segments:
        lines = []
        for seg in segments:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "").strip()
            lines.append(f"[{start:.1f}s - {end:.1f}s] {text}")
        return "\n".join(lines)
    return transcript_data.get("full_text", "")


def _strip_markdown_json(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _coerce_hashtags(value) -> list[str]:
    if isinstance(value, list):
        tags = [str(t).strip() for t in value if str(t).strip()]
    elif isinstance(value, str):
        tags = [t.strip() for t in re.split(r"[\s,]+", value) if t.strip()]
    else:
        tags = []
    normalized = []
    for tag in tags:
        tag = tag.lstrip("#").strip()
        if tag:
            normalized.append(f"#{tag}")
    return normalized[:8]


def _score_0_to_100(value, default: int = 60) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = default
    return max(1, min(100, score))


def _validate_and_buffer_clips(
    clips: list,
    video_duration: float,
    min_length: float,
    max_length: float,
) -> list:
    validated = []
    for clip in clips:
        try:
            start = float(clip.get("start_time", 0))
            end = float(clip.get("end_time", 0))
            title = str(clip.get("title", "Untitled Clip")).strip() or "Untitled Clip"
            reason = str(clip.get("reason", "")).strip()
            description = str(clip.get("description", "")).strip()
            hashtags = _coerce_hashtags(clip.get("hashtags", []))
            virality = _score_0_to_100(clip.get("virality_score", 60))
            hook_score = _score_0_to_100(clip.get("hook_score", virality))
            content_score = _score_0_to_100(clip.get("content_score", virality))
            clip_number = int(clip.get("clip_number", len(validated) + 1))

            if start < 0:
                start = 0.0
            if end > video_duration:
                end = video_duration
            if end <= start:
                continue

            # Allow a slightly longer clip when it completes the thought.
            soft_max = max_length * 1.2
            if (end - start) > soft_max:
                end = start + soft_max

            if (end - start) < min_length:
                continue

            start = max(0.0, start - BUFFER_SECONDS)
            end = min(video_duration, end + BUFFER_SECONDS)
            if (end - start) < min_length:
                continue

            validated.append(
                {
                    "clip_number": clip_number,
                    "start_time": round(start, 2),
                    "end_time": round(end, 2),
                    "title": title,
                    "reason": reason,
                    "description": description,
                    "hashtags": hashtags,
                    "virality_score": virality,
                    "hook_score": hook_score,
                    "content_score": content_score,
                }
            )
        except (TypeError, ValueError):
            continue

    validated.sort(
        key=lambda c: (
            c.get("virality_score", 0),
            c.get("content_score", 0),
            c.get("hook_score", 0),
        ),
        reverse=True,
    )
    for i, clip in enumerate(validated, start=1):
        clip["clip_number"] = i
    return validated


def _fallback_clips(
    transcript_data: dict,
    video_duration: float,
    num_clips: int,
    min_length: float,
    max_length: float,
) -> list:
    """Create basic complete-ish clips if the LLM returns too few usable clips."""
    segments = transcript_data.get("segments", [])
    if not segments:
        return []

    target = max(min_length, min(max_length, 90.0))
    chunks = []
    current = []
    start = None

    for seg in segments:
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", seg_start))
        if start is None:
            start = seg_start
        current.append(seg)
        duration = seg_end - start
        text = " ".join(s.get("text", "").strip() for s in current).strip()
        ends_cleanly = text.endswith((".", "!", "?"))
        if duration >= target and ends_cleanly:
            chunks.append((start, seg_end, text))
            current = []
            start = None

    if current and start is not None:
        end = float(current[-1].get("end", start + min_length))
        text = " ".join(s.get("text", "").strip() for s in current).strip()
        if end - start >= min_length:
            chunks.append((start, end, text))

    fallback = []
    for i, (start, end, text) in enumerate(chunks[:num_clips], start=1):
        title_words = text.split()[:8]
        title = " ".join(title_words).strip().rstrip(".,!?") or f"Clip {i}"
        fallback.append(
            {
                "clip_number": i,
                "start_time": start,
                "end_time": end,
                "title": title[:70],
                "reason": "Fallback clip built from a complete transcript section.",
                "description": text[:180].strip(),
                "hashtags": ["#shorts", "#viral", "#fyp"],
                "virality_score": max(50, 80 - i * 5),
                "hook_score": max(45, 75 - i * 5),
                "content_score": max(55, 85 - i * 5),
            }
        )
    return _validate_and_buffer_clips(fallback, video_duration, min_length, max_length)


def select_clips(
    transcript_data: dict,
    video_duration: float,
    num_clips: int = 5,
    min_length: float = DEFAULT_MIN_LENGTH,
    max_length: float = DEFAULT_MAX_LENGTH,
) -> list:
    """
    Use Groq Llama 3.3 70B to select the most viral-worthy highlight clips from a
    transcript, complete with a catchy title, a ready-to-post description,
    hashtags, and 0-100 scores.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if (
        not groq_api_key
        or groq_api_key == "your_groq_api_key_here"
    ) and not gemini_api_key:
        raise RuntimeError(
            "No AI provider is configured. Add GROQ_API_KEY or GEMINI_API_KEY to the .env file."
        )

    num_clips = max(1, min(10, int(num_clips)))
    min_length = max(5.0, float(min_length))
    max_length = max(min_length + 1.0, float(max_length))

    transcript_text = _build_transcript_prompt(transcript_data)
    if not transcript_text.strip():
        raise RuntimeError("Transcript is empty; cannot select clips.")

    prompt = f"""You are GPT-5.5 acting as a senior short-form video producer for TikTok, YouTube Shorts, and Instagram Reels.

Analyze this timestamped transcript and pick EXACTLY {num_clips} engaging, shareable, self-contained highlight moments when possible.

Video duration: {video_duration:.1f} seconds

Transcript:
{transcript_text}

Rules:
- IMPORTANT: Do not force fixed 25-second clips. Pick the natural beginning and ending of the conversation.
- A clip can be about 30 seconds, 1 minute, 2 minutes, or up to about {max_length:.0f} seconds if needed to complete the thought.
- Each clip should usually be at least {min_length:.0f} seconds, but prioritize complete communication over exact length.
- Clips must be fully contained within the video (0 to {video_duration:.1f} seconds).
- Start at the setup/context, not in the middle of a sentence. End after the answer/payoff/conclusion.
- Prefer moments with a strong hook, useful information, debate, emotion, surprise, insight, disagreement, story, or a complete answer.
- Avoid duplicate or overlapping clips.
- For each clip, write a punchy curiosity title, a ready-to-post description, 3 to 6 hashtags, and these scores from 1 to 100:
  - virality_score: chance of views/retention
  - hook_score: how quickly it grabs attention
  - content_score: how complete/useful/genuine the clip is
- Sort the array best-first by virality_score, then content_score.
- Respond ONLY with valid JSON — no explanation, no markdown, no code fences.

Return a JSON object in this exact shape:
{{
  "clips": [
    {{
      "clip_number": 1,
      "start_time": 12.5,
      "end_time": 47.3,
      "title": "Punchy hook title",
      "reason": "Why this moment is engaging",
      "description": "Ready-to-post caption for the clip.",
      "hashtags": ["#example", "#viral"],
      "virality_score": 87,
      "hook_score": 82,
      "content_score": 91
    }}
  ]
}}"""

    try:
        raw = ""
        provider_errors: list[str] = []

        if groq_api_key and groq_api_key != "your_groq_api_key_here":
            try:
                client = Groq(api_key=groq_api_key)
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content or ""
            except Exception as exc:
                provider_errors.append(f"Groq failed: {exc}")

        if not raw and gemini_api_key:
            if genai is None:
                provider_errors.append(
                    "Gemini fallback unavailable because google-generativeai is not installed."
                )
            else:
                try:
                    genai.configure(api_key=gemini_api_key)
                    model = genai.GenerativeModel("gemini-2.0-flash")
                    response = model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0.35,
                            "max_output_tokens": 4096,
                            "response_mime_type": "application/json",
                        },
                    )
                    raw = response.text or ""
                except Exception as exc:
                    provider_errors.append(f"Gemini failed: {exc}")

        if not raw:
            raise RuntimeError("; ".join(provider_errors) or "No AI provider returned text.")

        cleaned = _strip_markdown_json(raw)
        parsed = json.loads(cleaned)

        if isinstance(parsed, dict):
            clips = parsed.get("clips", [])
        elif isinstance(parsed, list):
            clips = parsed
        else:
            raise ValueError("LLM response is not valid clip JSON")

        validated = _validate_and_buffer_clips(
            clips, video_duration, min_length, max_length
        )
        if not validated:
            validated = _fallback_clips(
                transcript_data, video_duration, num_clips, min_length, max_length
            )
        if len(validated) < min(num_clips, 3):
            fallback = _fallback_clips(
                transcript_data, video_duration, num_clips, min_length, max_length
            )
            seen = {(c["start_time"], c["end_time"]) for c in validated}
            for clip in fallback:
                key = (clip["start_time"], clip["end_time"])
                if key not in seen:
                    validated.append(clip)
                    seen.add(key)
                if len(validated) >= num_clips:
                    break
            validated.sort(
                key=lambda c: (
                    c.get("virality_score", 0),
                    c.get("content_score", 0),
                    c.get("hook_score", 0),
                ),
                reverse=True,
            )
            for i, clip in enumerate(validated, start=1):
                clip["clip_number"] = i
        if not validated:
            raise RuntimeError("No valid clips found. Try a longer or clearer video.")
        return validated
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse LLM clip selection JSON: {exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Clip selection failed: {exc}") from exc
