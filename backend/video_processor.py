import subprocess
import zipfile
from pathlib import Path

from backend.utils import get_video_duration


def cut_clip(
    input_path: str,
    start_time: float,
    end_time: float,
    output_path: str,
    precise: bool = False,
) -> str:
    """
    Cut a clip from a video using ffmpeg.

    When ``precise`` is False (default) it uses fast stream-copy seeking, which
    is lossless and quick but snaps to the nearest keyframe. When ``precise`` is
    True it re-encodes with frame-accurate seeking so that burned captions stay
    perfectly in sync with the audio.
    """
    try:
        src = Path(input_path)
        dst = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        duration = max(end_time - start_time, 0.1)

        def _run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, capture_output=True, text=True, check=False)

        reencode_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_time),
            "-i",
            str(src),
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-avoid_negative_ts",
            "make_zero",
            str(dst),
        ]

        if precise:
            result = _run(reencode_cmd)
        else:
            copy_cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_time),
                "-i",
                str(src),
                "-t",
                str(duration),
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                str(dst),
            ]
            result = _run(copy_cmd)
            if result.returncode != 0:
                result = _run(reencode_cmd)

        if result.returncode != 0:
            raise RuntimeError(
                f"Clip cut failed: {result.stderr.strip() or result.stdout.strip()}"
            )

        if not dst.exists():
            raise RuntimeError("Clip cut completed but output file was not created")
        return str(dst)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to cut clip: {exc}") from exc


def convert_to_shorts(input_path: str, output_path: str) -> str:
    """
    Convert a video to 9:16 vertical format (1080x1920) using a blurred fill of
    the video itself as the background instead of black bars, which looks far
    more professional on TikTok / YouTube Shorts / Reels.
    """
    try:
        src = Path(input_path)
        dst = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        dst.parent.mkdir(parents=True, exist_ok=True)

        filter_complex = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=luma_radius=40:luma_power=2[bgb];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(dst),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Shorts conversion failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        if not dst.exists():
            raise RuntimeError(
                "Shorts conversion completed but output file was not created"
            )
        return str(dst)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to convert to shorts: {exc}") from exc


def normalize_audio(input_path: str, output_path: str) -> str:
    """Apply EBU R128 loudness normalization for consistent, platform-ready volume."""
    try:
        src = Path(input_path)
        dst = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(dst),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Audio normalization failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        if not dst.exists():
            raise RuntimeError(
                "Audio normalization completed but output file was not created"
            )
        return str(dst)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to normalize audio: {exc}") from exc


def apply_visual_cleanup(
    input_path: str,
    output_path: str,
    position: str = "top_left",
) -> str:
    """
    Mask a likely logo/channel-name corner with a subtle rounded-looking dark
    label. This is for visual cleanup/branding privacy only; it does not remove
    copyright obligations for third-party content.
    """
    try:
        src = Path(input_path)
        dst = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        positions = {
            "top_left": "x=28:y=28",
            "top_right": "x=w-388:y=28",
            "bottom_left": "x=28:y=h-178",
            "bottom_right": "x=w-388:y=h-178",
        }
        xy = positions.get(position, positions["top_left"])
        vf = f"drawbox={xy}:w=360:h=110:color=black@0.58:t=fill"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "copy",
            str(dst),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Visual cleanup failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        if not dst.exists():
            raise RuntimeError("Visual cleanup completed but output file was not created")
        return str(dst)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to apply visual cleanup: {exc}") from exc


def mix_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.12,
) -> str:
    """Mix background music softly under original video audio."""
    try:
        video = Path(video_path)
        music = Path(music_path)
        output = Path(output_path)

        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not music.exists():
            raise FileNotFoundError(f"Music file not found: {music_path}")

        output.parent.mkdir(parents=True, exist_ok=True)
        video_duration = get_video_duration(video)

        volume = max(0.02, min(0.35, float(music_volume)))
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{video_duration},"
            f"afade=t=in:st=0:d=1,afade=t=out:st={max(video_duration - 1, 0)}:d=1,"
            f"volume={volume}[music];"
            "[0:a]volume=1.0[voice];"
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(music),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Music mix failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        if not output.exists():
            raise RuntimeError("Music mix completed but output file was not created")
        return str(output)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to mix background music: {exc}") from exc


def create_zip(clip_paths: list, zip_output_path: str) -> str:
    """Zip all provided file paths into a single archive."""
    try:
        zip_path = Path(zip_output_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for clip in clip_paths:
                file_path = Path(clip)
                if file_path.exists() and file_path.is_file():
                    zf.write(file_path, arcname=file_path.name)

        if not zip_path.exists():
            raise RuntimeError("ZIP creation completed but file was not created")
        return str(zip_path)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to create ZIP: {exc}") from exc
