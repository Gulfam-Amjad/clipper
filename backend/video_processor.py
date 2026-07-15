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


def _has_audio_stream(video: Path) -> bool:
    """Return True if the given media file has at least one audio stream."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def mix_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.12,
) -> str:
    """
    Mix background music under the original video audio.

    Uses ``amix`` with ``normalize=0`` so the original voice stays at full
    volume and the music sits underneath at the requested level (the default
    ffmpeg behaviour normalizes every input, which makes the music almost
    inaudible). If the clip has no audio track, the music becomes the audio.
    """
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
        fade_out_start = max(video_duration - 1.0, 0.0)
        volume = max(0.02, min(0.6, float(music_volume)))

        music_chain = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{video_duration},"
            f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start}:d=1,"
            f"volume={volume}[music]"
        )

        if _has_audio_stream(video):
            filter_complex = (
                f"{music_chain};"
                "[0:a][music]amix=inputs=2:duration=first:"
                "dropout_transition=2:normalize=0[aout]"
            )
        else:
            # No original audio — the looped, trimmed music is the audio track.
            filter_complex = music_chain.replace("[music]", "[aout]")

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
            "-b:a",
            "192k",
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


def apply_copyright_safe(
    input_path: str,
    output_path: str,
    mirror: bool = False,
) -> str:
    """
    Apply subtle, quality-preserving transforms that reduce automated
    copyright/content-ID matching: a small zoom-in crop, a light color grade,
    and an optional horizontal mirror. These do not change timing, so burned
    captions stay in sync.

    Note: this reduces fingerprint matching but does NOT grant any legal right
    to reuse third-party content. Only use on content you own or are licensed
    to reuse.
    """
    try:
        src = Path(input_path)
        dst = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        dst.parent.mkdir(parents=True, exist_ok=True)

        chain = (
            "scale=iw*1.06:ih*1.06,"
            "crop=iw/1.06:ih/1.06,"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            "eq=contrast=1.05:saturation=1.08:brightness=0.02"
        )
        if mirror:
            chain += ",hflip"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            chain,
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
                f"Copyright-safe transform failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        if not dst.exists():
            raise RuntimeError("Copyright-safe transform produced no output file")
        return str(dst)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to apply copyright-safe transform: {exc}") from exc


def overlay_logo(
    input_path: str,
    logo_path: str,
    output_path: str,
    position: str = "top_left",
    scale_width: int = 300,
) -> str:
    """
    Overlay a user-supplied logo/watermark image (PNG with transparency
    recommended) onto a corner of the video, on top of any existing channel
    logo. Pair with ``apply_visual_cleanup`` to first mask the original logo.
    """
    try:
        src = Path(input_path)
        logo = Path(logo_path)
        dst = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")
        if not logo.exists():
            raise FileNotFoundError(f"Logo image not found: {logo_path}")

        dst.parent.mkdir(parents=True, exist_ok=True)

        margin = 40
        positions = {
            "top_left": f"x={margin}:y={margin}",
            "top_right": f"x=main_w-overlay_w-{margin}:y={margin}",
            "bottom_left": f"x={margin}:y=main_h-overlay_h-{margin}",
            "bottom_right": f"x=main_w-overlay_w-{margin}:y=main_h-overlay_h-{margin}",
        }
        xy = positions.get(position, positions["top_left"])

        filter_complex = (
            f"[1:v]scale={int(scale_width)}:-1[lg];"
            f"[0:v][lg]overlay={xy}:format=auto[v]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-i",
            str(logo),
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
            "copy",
            str(dst),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Logo overlay failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        if not dst.exists():
            raise RuntimeError("Logo overlay produced no output file")
        return str(dst)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to overlay logo: {exc}") from exc


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
