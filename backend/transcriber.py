import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from backend.utils import get_audio_duration

load_dotenv()

# Groq's Whisper endpoint limits upload size. Mono 16 kHz s16le WAV is
# ~32 KB/s, so a 600 s chunk is ~19 MB — safely under the limit.
CHUNK_SECONDS = 600.0


def _extract_audio(video_path: Path) -> Path:
    """Extract mono 16kHz WAV audio from video for Whisper."""
    temp_dir = Path(tempfile.gettempdir())
    audio_path = temp_dir / f"clipper_audio_{video_path.stem}_{uuid.uuid4().hex}.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    if not audio_path.exists():
        raise RuntimeError("Audio extraction completed but output file was not created")
    return audio_path


def _slice_audio(audio_path: Path, start: float, duration: float) -> Path:
    """Extract a sub-section of an existing WAV file."""
    temp_dir = Path(tempfile.gettempdir())
    chunk_path = temp_dir / f"clipper_chunk_{uuid.uuid4().hex}.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(audio_path),
        "-c",
        "copy",
        str(chunk_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not chunk_path.exists():
        raise RuntimeError(
            f"Audio chunking failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return chunk_path


def _transcribe_file(client: Groq, audio_path: Path) -> dict:
    """Send a single audio file to Groq Whisper and return the raw response dict."""
    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            file=(audio_path.name, audio_file.read()),
            model="whisper-large-v3",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
    return response.model_dump() if hasattr(response, "model_dump") else dict(response)


def _collect(data: dict, offset: float) -> tuple[str, list, list]:
    """Extract text/segments/words from a raw response, shifting times by offset."""
    text = data.get("text", "").strip()
    segments = [
        {
            "start": float(seg.get("start", 0)) + offset,
            "end": float(seg.get("end", 0)) + offset,
            "text": seg.get("text", "").strip(),
        }
        for seg in data.get("segments", [])
    ]
    words = [
        {
            "word": w.get("word", "").strip(),
            "start": float(w.get("start", 0)) + offset,
            "end": float(w.get("end", 0)) + offset,
        }
        for w in data.get("words", [])
    ]
    return text, segments, words


def transcribe_video(video_path: str) -> dict:
    """
    Extract audio from a video and transcribe with Groq Whisper. Long videos are
    split into chunks and stitched back together with correct time offsets.
    Returns dict with full_text, segments, and words.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        raise RuntimeError("GROQ_API_KEY is not set. Add your key to the .env file.")

    audio_path: Path | None = None
    temp_chunks: list[Path] = []
    try:
        audio_path = _extract_audio(path)
        client = Groq(api_key=api_key)

        try:
            total_duration = get_audio_duration(audio_path)
        except Exception:
            total_duration = 0.0

        all_text: list[str] = []
        all_segments: list = []
        all_words: list = []

        if total_duration <= CHUNK_SECONDS or total_duration <= 0:
            data = _transcribe_file(client, audio_path)
            text, segments, words = _collect(data, 0.0)
            all_text.append(text)
            all_segments.extend(segments)
            all_words.extend(words)
        else:
            offset = 0.0
            while offset < total_duration:
                chunk_len = min(CHUNK_SECONDS, total_duration - offset)
                chunk_path = _slice_audio(audio_path, offset, chunk_len)
                temp_chunks.append(chunk_path)
                data = _transcribe_file(client, chunk_path)
                text, segments, words = _collect(data, offset)
                if text:
                    all_text.append(text)
                all_segments.extend(segments)
                all_words.extend(words)
                offset += chunk_len

        return {
            "full_text": " ".join(t for t in all_text if t).strip(),
            "segments": all_segments,
            "words": all_words,
        }
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Groq transcription failed: {exc}") from exc
    finally:
        for chunk in temp_chunks:
            try:
                chunk.unlink()
            except OSError:
                pass
        if audio_path and audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass
