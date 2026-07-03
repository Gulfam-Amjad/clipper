import subprocess
from pathlib import Path

from backend.utils import (
    get_video_dimensions,
    seconds_to_ass_time,
    seconds_to_srt_time,
)

MAX_WORDS_PER_LINE = 5
MAX_LINE_DURATION = 2.5


def _extract_words_in_window(
    transcript_data: dict,
    clip_start: float | None,
    clip_end: float | None,
) -> list[dict]:
    """
    Return word entries that fall inside [clip_start, clip_end], with timestamps
    re-based so the clip starts at 0. If no word timestamps exist, fall back to
    evenly spreading each segment's words across its duration.
    """
    words = transcript_data.get("words", [])

    if not words:
        segments = transcript_data.get("segments", [])
        words = []
        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            seg_words = text.split()
            if not seg_words:
                continue
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start + 1))
            duration = max(end - start, 0.1)
            step = duration / len(seg_words)
            for i, w in enumerate(seg_words):
                words.append(
                    {
                        "word": w,
                        "start": start + i * step,
                        "end": start + (i + 1) * step,
                    }
                )

    if clip_start is None:
        clip_start = 0.0

    windowed: list[dict] = []
    for entry in words:
        word = str(entry.get("word", "")).strip()
        if not word:
            continue
        w_start = float(entry.get("start", 0))
        w_end = float(entry.get("end", w_start))

        # Keep words that overlap the clip window at all.
        if w_end < clip_start:
            continue
        if clip_end is not None and w_start > clip_end:
            continue

        rel_start = max(0.0, w_start - clip_start)
        rel_end = max(rel_start, w_end - clip_start)
        windowed.append({"word": word, "start": rel_start, "end": rel_end})

    return windowed


def _group_into_lines(words: list[dict]) -> list[list[dict]]:
    """Group words into short caption lines by word count and duration."""
    lines: list[list[dict]] = []
    current: list[dict] = []
    line_start: float | None = None

    for entry in words:
        if line_start is None:
            line_start = entry["start"]
        current.append(entry)
        duration = entry["end"] - line_start

        if len(current) >= MAX_WORDS_PER_LINE or duration >= MAX_LINE_DURATION:
            lines.append(current)
            current = []
            line_start = None

    if current:
        lines.append(current)
    return lines


def generate_srt(
    transcript_data: dict,
    output_path: str,
    clip_start: float | None = None,
    clip_end: float | None = None,
) -> str:
    """
    Write a plain .srt file for the given clip window (max 7 words / 3 seconds
    per line). Timestamps are re-based to the clip start.
    """
    try:
        words = _extract_words_in_window(transcript_data, clip_start, clip_end)

        chunks: list[dict] = []
        current_words: list[str] = []
        chunk_start: float | None = None
        chunk_end: float = 0.0

        for entry in words:
            if chunk_start is None:
                chunk_start = entry["start"]
            current_words.append(entry["word"])
            chunk_end = entry["end"]

            duration = chunk_end - chunk_start
            if len(current_words) >= 7 or duration >= 3.0:
                chunks.append(
                    {"start": chunk_start, "end": chunk_end, "text": " ".join(current_words)}
                )
                current_words = []
                chunk_start = None

        if current_words and chunk_start is not None:
            chunks.append(
                {"start": chunk_start, "end": chunk_end, "text": " ".join(current_words)}
            )

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            lines.append(str(idx))
            lines.append(
                f"{seconds_to_srt_time(chunk['start'])} --> "
                f"{seconds_to_srt_time(chunk['end'])}"
            )
            lines.append(chunk["text"])
            lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")
        return str(out)
    except Exception as exc:
        raise RuntimeError(f"Failed to generate SRT file: {exc}") from exc


def _ass_escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def generate_ass(
    transcript_data: dict,
    output_path: str,
    width: int,
    height: int,
    clip_start: float | None = None,
    clip_end: float | None = None,
    highlight_color: str = "&H0000FFFF&",
) -> str:
    """
    Generate an animated word-by-word (karaoke-style) .ass subtitle file sized
    to the target video. The currently spoken word is highlighted. Timestamps
    are re-based so the clip starts at 0.
    """
    try:
        words = _extract_words_in_window(transcript_data, clip_start, clip_end)
        lines = _group_into_lines(words)

        font_size = max(24, round(height * 0.055))
        outline = max(2, round(font_size * 0.09))
        margin_v = round(height * 0.14)
        margin_h = round(width * 0.06)

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events: list[str] = []
        for line in lines:
            if not line:
                continue
            for j, active in enumerate(line):
                start = active["start"]
                # Keep the line on screen continuously: end at the next word's
                # start, or this word's end if it's the last in the line.
                if j + 1 < len(line):
                    end = max(line[j + 1]["start"], start + 0.05)
                else:
                    end = max(active["end"], start + 0.2)

                parts: list[str] = []
                for k, w in enumerate(line):
                    token = _ass_escape(w["word"])
                    if k == j:
                        parts.append(
                            f"{{\\1c{highlight_color}}}{token}{{\\1c&H00FFFFFF&}}"
                        )
                    else:
                        parts.append(token)
                text = " ".join(parts)

                events.append(
                    f"Dialogue: 0,{seconds_to_ass_time(start)},"
                    f"{seconds_to_ass_time(end)},Base,,0,0,0,,{text}"
                )

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
        return str(out)
    except Exception as exc:
        raise RuntimeError(f"Failed to generate ASS file: {exc}") from exc


def _escape_filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def burn_captions(
    video_path: str,
    transcript_data: dict,
    output_path: str,
    clip_start: float | None = None,
    clip_end: float | None = None,
) -> str:
    """
    Generate animated word-by-word captions matched to the clip window and burn
    them into the video with ffmpeg.
    """
    try:
        video = Path(video_path)
        output = Path(output_path)
        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            width, height = get_video_dimensions(video)
        except Exception:
            width, height = 1080, 1920

        ass_path = output.parent / f"{video.stem}_captions.ass"
        generate_ass(
            transcript_data,
            str(ass_path),
            width,
            height,
            clip_start=clip_start,
            clip_end=clip_end,
        )

        ass_escaped = _escape_filter_path(ass_path)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"ass='{ass_escaped}'",
            "-c:a",
            "copy",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Caption burn failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        if not output.exists():
            raise RuntimeError("Caption burn completed but output file was not created")
        return str(output)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to burn captions: {exc}") from exc


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> str:
    """Burn a pre-made SRT file into a video using ffmpeg (legacy helper)."""
    try:
        video = Path(video_path)
        srt = Path(srt_path)
        output = Path(output_path)

        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not srt.exists():
            raise FileNotFoundError(f"SRT not found: {srt_path}")

        output.parent.mkdir(parents=True, exist_ok=True)

        srt_escaped = _escape_filter_path(srt)
        subtitle_filter = (
            f"subtitles='{srt_escaped}':"
            "force_style='FontName=Arial,FontSize=18,Bold=1,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "Outline=2,Alignment=2,MarginV=30'"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vf",
            subtitle_filter,
            "-c:a",
            "copy",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Subtitle burn failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        if not output.exists():
            raise RuntimeError("Subtitle burn completed but output file was not created")
        return str(output)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to burn subtitles: {exc}") from exc
