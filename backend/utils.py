import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
MUSIC_DIR = BASE_DIR / "music"


def get_video_duration(filepath: str | Path) -> float:
    """Return video duration in seconds using ffprobe."""
    try:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {path}")

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffprobe failed: {result.stderr.strip() or result.stdout.strip()}"
            )

        duration = float(result.stdout.strip())
        if duration <= 0:
            raise ValueError(f"Invalid duration returned: {duration}")
        return duration
    except (ValueError, FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to get video duration: {exc}") from exc


def get_video_dimensions(filepath: str | Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream using ffprobe."""
    try:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {path}")

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffprobe failed: {result.stderr.strip() or result.stdout.strip()}"
            )

        raw = result.stdout.strip().split("\n")[0]
        width_str, height_str = raw.lower().split("x")
        width, height = int(width_str), int(height_str)
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid dimensions returned: {raw}")
        return width, height
    except (ValueError, FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to get video dimensions: {exc}") from exc


def get_audio_duration(filepath: str | Path) -> float:
    """Return media duration in seconds using ffprobe (works for audio too)."""
    return get_video_duration(filepath)


def format_timestamp(seconds: float) -> str:
    """Convert float seconds to HH:MM:SS string."""
    try:
        total = max(0, int(seconds))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    except Exception as exc:
        raise ValueError(f"Failed to format timestamp: {exc}") from exc


def seconds_to_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT format HH:MM:SS,mmm."""
    try:
        if seconds < 0:
            seconds = 0.0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis >= 1000:
            millis = 0
            secs += 1
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    except Exception as exc:
        raise ValueError(f"Failed to convert to SRT time: {exc}") from exc


def seconds_to_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS format H:MM:SS.cc (centiseconds)."""
    try:
        if seconds < 0:
            seconds = 0.0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int(round((seconds - int(seconds)) * 100))
        if centis >= 100:
            centis = 0
            secs += 1
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"
    except Exception as exc:
        raise ValueError(f"Failed to convert to ASS time: {exc}") from exc


def ensure_dirs() -> None:
    """Create uploads/, outputs/, and music/ if they don't exist."""
    try:
        for folder in (UPLOADS_DIR, OUTPUTS_DIR, MUSIC_DIR):
            folder.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to create required directories: {exc}") from exc


def cleanup_old_files(folder: str | Path, max_age_minutes: int = 60) -> None:
    """Delete files older than max_age_minutes from a folder."""
    try:
        target = Path(folder)
        if not target.exists():
            return

        cutoff = time.time() - (max_age_minutes * 60)
        for item in target.iterdir():
            if item.name == ".gitkeep":
                continue
            try:
                mtime = item.stat().st_mtime
                if mtime < cutoff:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        import shutil

                        shutil.rmtree(item, ignore_errors=True)
            except OSError:
                continue
    except Exception as exc:
        raise RuntimeError(f"Failed to cleanup old files in {folder}: {exc}") from exc
