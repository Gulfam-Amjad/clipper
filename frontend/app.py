"""
VideoClipper Frontend - Streamlit Application
User interface for video uploading, processing status tracking, and clip download
"""

import os
import time
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ═══════════════ CONSTANTS ═══════════════
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
MUSIC_STYLE_LABELS = {"phonk": "Phonk", "lofi": "Lofi", "epic": "Epic", "chill": "Chill", "upbeat": "Upbeat"}
FORMAT_PRESETS = {}
SUPPORTED_LANGUAGES_FALLBACK = {"en": "English", "ur": "Urdu", "ar": "Arabic"}
POLL_INTERVAL_SECONDS = 3
MAX_FILE_SIZE_MB = 500

# Page configuration
st.set_page_config(
    page_title="VideoClipper 🎬",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Session state will be initialized after helper functions are defined

# Custom CSS for better styling
st.markdown(
    """
    <style>
    .main-header {
        text-align: center;
        padding: 20px 0;
        border-bottom: 2px solid #FF0000;
    }
    .status-badge {
        padding: 5px 10px;
        border-radius: 5px;
        font-weight: bold;
        display: inline-block;
    }
    .status-processing {
        background-color: #FFA500;
        color: white;
    }
    .status-done {
        background-color: #28a745;
        color: white;
    }
    .status-error {
        background-color: #dc3545;
        color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state():
    defaults = {
        "job_id": None,
        "job_history": [],
        "processing": False,
        "mode": "Upload Video",
        "guidance": "",
        "generate_shorts": False,
        "language": "en",
        "preview_cache": {},
        "filter_output_by_clip": {},
        "show_preview_for_clip": {},
        "copy_text": "",
        "last_upload": None,
        "confirm_new_job": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# Initialize session state now that helper functions are defined
init_session_state()


def safe_rerun():
    st.rerun()


@st.cache_data(ttl=3600)
def load_filter_presets():
    try:
        r = requests.get(f"{BACKEND_URL}/filter-presets", timeout=5)
        if r.status_code == 200:
            return r.json()
        return {}
    except Exception:
        return {}


def check_backend_health():
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def backend_unavailable_message(action: str) -> str:
    return (
        f"{action} needs the backend at {BACKEND_URL}, but it is not reachable. "
        "Start it with: cd backend && python main.py"
    )


def fetch_backend_bytes(url: str, action: str):
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.content

        if response.status_code == 404:
            st.error(f"{action} is not available yet.")
        else:
            detail = response.text or f"HTTP {response.status_code}"
            st.error(f"{action} failed: {detail}")
        return None

    except requests.exceptions.ConnectionError:
        st.error(backend_unavailable_message(action))
        return None
    except requests.exceptions.Timeout:
        st.error(f"{action} timed out. Try again in a moment.")
        return None
    except Exception as exc:
        st.error(f"{action} failed: {str(exc)}")
        return None


def fetch_json(url: str, params=None, json_body=None, timeout=30):
    try:
        if json_body is not None:
            response = requests.post(url, json=json_body, timeout=timeout)
        else:
            response = requests.get(url, params=params, timeout=timeout)

        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def add_job_to_history(job_id, source, guidance, language, generate_shorts):
    entry = {
        "job_id": job_id,
        "source": source,
        "guidance": guidance,
        "language": language,
        "generate_shorts": generate_shorts,
        "timestamp": datetime.utcnow().isoformat(),
    }
    history = [item for item in st.session_state.job_history if item["job_id"] != job_id]
    history.append(entry)
    st.session_state.job_history = history[-10:]


def upload_video(video_file, guidance, generate_shorts, language: str = "en"):
    try:
        # Accept either a Streamlit UploadedFile or a persisted session dict
        if isinstance(video_file, dict):
            files = {
                "video": (
                    video_file.get("name"),
                    video_file.get("bytes"),
                    video_file.get("type", "video/mp4"),
                )
            }
        else:
            files = {"video": (video_file.name, video_file.getvalue(), video_file.type or "video/mp4")}
        data = {
            "guidance": guidance,
            "shorts_mode": "true" if generate_shorts else "false",
            "language": language,
        }

        response = requests.post(
            f"{BACKEND_URL}/process",
            files=files,
            data=data,
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json()
            return result.get("job_id")

        try:
            error_detail = response.json().get("detail", "Unknown error")
        except Exception:
            error_detail = response.text or f"HTTP {response.status_code}"
        st.error(f"❌ Failed to process video: {error_detail}")
        return None
    except requests.exceptions.Timeout:
        st.error("❌ Request timed out. Please try again.")
        return None
    except Exception as exc:
        st.error(f"❌ Error uploading video: {exc}")
        return None


def process_youtube_url(youtube_url, guidance, generate_shorts, language: str = "en"):
    try:
        data = {
            "youtube_url": youtube_url,
            "guidance": guidance,
            "shorts_mode": "true" if generate_shorts else "false",
            "language": language,
        }

        response = requests.post(
            f"{BACKEND_URL}/process-url",
            data=data,
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json()
            return result.get("job_id")

        try:
            error_detail = response.json().get("detail", "Unknown error")
        except Exception:
            error_detail = response.text or f"HTTP {response.status_code}"
        st.error(f"❌ Failed to process YouTube URL: {error_detail}")
        return None
    except requests.exceptions.Timeout:
        st.error("❌ Request timed out. Please try again.")
        return None
    except Exception as exc:
        st.error(f"❌ Error processing YouTube URL: {exc}")
        return None


def get_job_status(job_id):
    try:
        response = requests.get(f"{BACKEND_URL}/status/{job_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as exc:
        st.error(f"❌ Error fetching job status: {exc}")
        return None


def download_clip(job_id, filename, is_shorts=False):
    if is_shorts:
        url = f"{BACKEND_URL}/download-shorts/{job_id}/{filename}"
        action = "Shorts download"
    else:
        url = f"{BACKEND_URL}/download/{job_id}/{filename}"
        action = "Clip download"
    return fetch_backend_bytes(url, action)


def cleanup_job(job_id):
    try:
        response = requests.delete(f"{BACKEND_URL}/cleanup/{job_id}", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_video_info(youtube_url):
    try:
        response = requests.get(
            f"{BACKEND_URL}/video-info",
            params={"url": youtube_url},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def render_sidebar():
    with st.sidebar:
        st.title("VideoClipper")
        st.markdown("Upload or analyze a video and download generated clips.")

        st.radio(
            "Processing Mode",
            ["Upload Video", "YouTube URL"],
            key="mode",
            help="Select how you want to provide the source video.",
        )

        st.text_area(
            "Guidance",
            value=st.session_state.guidance,
            placeholder="Describe the content you want, e.g. funny clips or educational highlights",
            max_chars=500,
            key="guidance",
        )

        st.checkbox(
            "Generate YouTube Shorts (9:16)",
            value=st.session_state.generate_shorts,
            key="generate_shorts",
        )

        languages = {"en": "English", "ur": "Urdu", "ar": "Arabic"}
        try:
            response = requests.get(f"{BACKEND_URL}/languages", timeout=5)
            if response.status_code == 200:
                languages = response.json()
        except Exception:
            pass

        st.selectbox(
            "Video language",
            options=list(languages.keys()),
            format_func=lambda key: languages.get(key, key),
            index=list(languages.keys()).index(st.session_state.language) if st.session_state.language in languages else 0,
            key="language",
        )

        st.divider()
        with st.expander("Recent jobs", expanded=True):
            if not st.session_state.job_history:
                st.info("No recent jobs yet.")
            for entry in reversed(st.session_state.job_history):
                timestamp = datetime.fromisoformat(entry["timestamp"]).strftime("%b %d %H:%M UTC")
                st.markdown(f"**{entry['source']}** — {timestamp}")
                st.write(f"Guidance: {entry['guidance'] or 'None'}")
                st.write(f"Language: {entry['language']} — Shorts: {entry['generate_shorts']}")
                if st.button(f"Open {entry['job_id'][-8:]}", key=f"open_{entry['job_id']}"):
                    st.session_state.job_id = entry["job_id"]
                    safe_rerun()
                st.markdown("---")


def render_status_badge(status):
    if status == "done":
        return "✅ COMPLETED", "status-done"
    if status in ["error", "failed"]:
        return "❌ ERROR", "status-error"
    return f"⏳ {status.upper()}", "status-processing"


def render_footer():
    st.divider()
    st.markdown(
        """
        <div style="text-align: center; color: gray; font-size: 12px;">
            <p>VideoClipper 🎬 - AI-powered video clip generator</p>
            <p>Powered by Groq Whisper & Llama 3.3</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    init_session_state()

    st.markdown(
        '<div class="main-header"><h1>🎬 VideoClipper - AI-Powered Video Clip Generator</h1></div>',
        unsafe_allow_html=True,
    )

    backend_available = check_backend_health()
    if not backend_available:
        st.warning(
            f"Backend is offline at {BACKEND_URL}. Processing, preview, and downloads require the backend."
        )
        st.info("Start it with: cd backend && python main.py")

    render_sidebar()

    if st.session_state.job_id is None:
        st.subheader("Upload and process your video")
        if st.session_state.mode == "Upload Video":
            left, right = st.columns([2, 1])
            with left:
                video_file = st.file_uploader(
                    "Choose a video file",
                    type=["mp4", "mov", "avi", "mkv"],
                    help="Maximum size: 500MB",
                )

                if video_file is not None:
                    # Persist the uploaded bytes in session so retries don't require re-upload
                    try:
                        b = video_file.getvalue()
                        st.session_state.last_upload = {"name": video_file.name, "bytes": b, "type": video_file.type}
                    except Exception:
                        st.session_state.last_upload = None

                    st.video(video_file)
                    st.caption("Local preview")

                    preview_key = f"preview_{(video_file.name if hasattr(video_file, 'name') else st.session_state.get('last_upload', {}).get('name',''))}"
                    if preview_key not in st.session_state.preview_cache and backend_available:
                        with st.spinner("Requesting preview metadata..."):
                            try:
                                response = requests.post(
                                    f"{BACKEND_URL}/preview-upload",
                                    files={
                                        "video": (
                                            video_file.name,
                                            video_file.getvalue(),
                                            video_file.type or "video/mp4",
                                        )
                                    },
                                    timeout=30,
                                )
                                if response.status_code == 200:
                                    st.session_state.preview_cache[preview_key] = response.json()
                            except Exception:
                                pass

                    preview_data = st.session_state.preview_cache.get(preview_key)
                    if preview_data:
                        metadata = preview_data.get("metadata", {})
                        warnings = preview_data.get("warnings", [])
                        st.markdown("**Video metadata**")
                        st.write(f"Duration: {metadata.get('duration_str', 'Unknown')}")
                        st.write(f"Resolution: {metadata.get('width', 0)}×{metadata.get('height', 0)}")
                        st.write(f"FPS: {metadata.get('fps', 0):.1f}")
                        st.write(f"Size: {metadata.get('file_size_mb', 0):.1f} MB")
                        st.write(f"Audio: {'Yes' if metadata.get('has_audio') else 'No'}")
                        for warning in warnings:
                            st.warning(f"⚠️ {warning}")
                else:
                    st.info("Select a video file to upload and process.")

            with right:
                if st.button("🚀 Process Video", key="process_video_btn", use_container_width=True, disabled=not backend_available):
                    # Use persisted upload if available, otherwise use the freshly selected file
                    source = "Upload"
                    file_payload = None
                    if st.session_state.get("last_upload") is not None:
                        file_payload = st.session_state.last_upload
                    elif video_file is not None:
                        file_payload = video_file

                    if file_payload is None:
                        st.warning("Please select a file before processing.")
                    else:
                        with st.spinner("Uploading video and starting processing..."):
                            job_id = upload_video(
                                file_payload,
                                st.session_state.guidance,
                                st.session_state.generate_shorts,
                                st.session_state.language,
                            )
                            if job_id:
                                st.session_state.job_id = job_id
                                add_job_to_history(
                                    job_id,
                                    source,
                                    st.session_state.guidance,
                                    st.session_state.language,
                                    st.session_state.generate_shorts,
                                )
                                safe_rerun()

        else:
            left, right = st.columns([2, 1])
            with left:
                youtube_url = st.text_input(
                    "YouTube URL",
                    placeholder="https://www.youtube.com/watch?v=...",
                    help="Paste a valid YouTube link",
                    key="youtube_url",
                )

                if youtube_url and backend_available:
                    with st.spinner("Fetching YouTube video info..."):
                        info = get_video_info(youtube_url)
                    if info:
                        st.markdown("**Video info**")
                        st.write(f"Title: {info.get('title', 'Unknown')}")
                        duration = info.get('duration', 0)
                        st.write(f"Duration: {duration // 60} min")
                        st.write(f"Channel: {info.get('uploader', 'Unknown')}")

            with right:
                if st.button("🚀 Process URL", key="process_url_btn", use_container_width=True, disabled=not backend_available):
                    youtube_url = st.session_state.get("youtube_url", "") if "youtube_url" in st.session_state else ""
                    if not youtube_url:
                        st.warning("Please enter a YouTube URL first.")
                    else:
                        with st.spinner("Submitting URL for processing..."):
                            job_id = process_youtube_url(
                                youtube_url,
                                st.session_state.guidance,
                                st.session_state.generate_shorts,
                                st.session_state.language,
                            )
                            if job_id:
                                st.session_state.job_id = job_id
                                add_job_to_history(
                                    job_id,
                                    "YouTube URL",
                                    st.session_state.guidance,
                                    st.session_state.language,
                                    st.session_state.generate_shorts,
                                )
                                safe_rerun()

            st.info("Use a public YouTube URL and wait a moment for the backend to fetch and analyze the video.")

    else:
        job_id = st.session_state.job_id
        st.subheader(f"Processing Job: {job_id[:8]}")

        status_data = get_job_status(job_id)
        if status_data is None:
            st.error("Unable to retrieve job status. The job may have expired or the backend may be offline.")
            if st.button("Start a new job", use_container_width=True):
                st.session_state.job_id = None
                safe_rerun()
            render_footer()
            return

        status = status_data.get("status", "unknown")
        progress = status_data.get("progress", 0)
        message = status_data.get("message") or status_data.get("current_step", "Processing...")

        status_text, status_class = render_status_badge(status)
        st.markdown(
            f'<p style="font-size: 18px;"><span class="status-badge {status_class}">{status_text}</span></p>',
            unsafe_allow_html=True,
        )
        st.progress(min(progress / 100.0, 1.0))
        st.write(f"**Progress:** {progress}% — {message}")

        buttons = st.columns([1, 1, 2])
        if buttons[0].button("🔄 Refresh Status"):
            safe_rerun()
        if buttons[1].button("🏠 New Job"):
            # require confirmation to avoid accidental loss
            st.session_state.confirm_new_job = True

        if st.session_state.get("confirm_new_job"):
            st.warning("This will delete temporary files for the current job. Confirm to continue.")
            c1, c2 = st.columns([1, 1])
            if c1.button("Confirm New Job"):
                cleanup_job(job_id)
                st.session_state.job_id = None
                st.session_state.confirm_new_job = False
                safe_rerun()
            if c2.button("Cancel"):
                st.session_state.confirm_new_job = False
                safe_rerun()

        if not backend_available:
            st.error(backend_unavailable_message("Status and download actions"))
            render_footer()
            return

        st.divider()

        if status == "done":
            st.success("✅ Processing completed successfully!")
            clips = status_data.get("clips", [])
            if clips:
                st.subheader(f"Generated Clips ({len(clips)})")
                for idx, clip in enumerate(clips, start=1):
                    filename = clip.get("filename", "")
                    title = clip.get("title", f"Clip {idx}")
                    start_ts = clip.get("start", 0)
                    end_ts = clip.get("end", 0)
                    duration = max(end_ts - start_ts, 0)
                    viral_score = clip.get("combined_viral_score", 0)

                    with st.container():
                        c1, c2, c3 = st.columns([3, 1, 1])
                        with c1:
                            st.markdown(f"**{title}**")
                            st.write(f"⏱ {start_ts:.1f}s – {end_ts:.1f}s ({duration:.1f}s)")
                            st.write(f"Viral score: {viral_score}/100")
                            if clip.get("viral_llm"):
                                platform_fit = clip["viral_llm"].get("platform_fit", {})
                                if platform_fit:
                                    pcols = st.columns(3)
                                    pcols[0].metric("YouTube", f"{platform_fit.get('youtube_shorts', 0)}%")
                                    pcols[1].metric("TikTok", f"{platform_fit.get('tiktok', 0)}%")
                                    pcols[2].metric("Instagram", f"{platform_fit.get('instagram', 0)}%")
                                improvement = clip["viral_llm"].get("improvement")
                                if improvement:
                                    st.caption(f"💡 {improvement}")

                        with c2:
                            if st.button("⬇ Download clip", key=f"download_clip_{job_id}_{idx}"):
                                clip_bytes = download_clip(job_id, filename)
                                if clip_bytes:
                                    st.download_button(
                                        "Download now",
                                        clip_bytes,
                                        file_name=filename,
                                        mime="video/mp4",
                                        key=f"download_button_{job_id}_{idx}",
                                    )

                            presets = load_filter_presets()
                            preset_names = ["custom"] + list(presets.keys())
                            selected_preset = st.selectbox(
                                "Preset",
                                preset_names,
                                key=f"preset_{job_id}_{idx}",
                            )
                            if selected_preset != "custom" and selected_preset in presets:
                                preset_values = presets[selected_preset]
                            else:
                                preset_values = {}

                            brightness = st.slider(
                                "Brightness",
                                -0.5,
                                0.5,
                                float(preset_values.get("brightness", 0.0)),
                                0.05,
                                key=f"brightness_{job_id}_{idx}",
                            )
                            contrast = st.slider(
                                "Contrast",
                                0.5,
                                2.0,
                                float(preset_values.get("contrast", 1.0)),
                                0.05,
                                key=f"contrast_{job_id}_{idx}",
                            )
                            saturation = st.slider(
                                "Saturation",
                                0.0,
                                3.0,
                                float(preset_values.get("saturation", 1.0)),
                                0.1,
                                key=f"saturation_{job_id}_{idx}",
                            )
                            hue = st.slider(
                                "Hue shift",
                                -180,
                                180,
                                int(preset_values.get("hue", 0)),
                                5,
                                key=f"hue_{job_id}_{idx}",
                            )
                            sharpness = st.slider(
                                "Sharpness",
                                0.0,
                                1.5,
                                float(preset_values.get("sharpness", 0.0)),
                                0.1,
                                key=f"sharpness_{job_id}_{idx}",
                            )
                            vignette = st.slider(
                                "Vignette",
                                0.0,
                                1.0,
                                float(preset_values.get("vignette", 0.0)),
                                0.1,
                                key=f"vignette_{job_id}_{idx}",
                            )
                            fade_in = st.checkbox(
                                "Fade in",
                                value=bool(preset_values.get("fade_in", True)),
                                key=f"fade_in_{job_id}_{idx}",
                            )
                            fade_out = st.checkbox(
                                "Fade out",
                                value=bool(preset_values.get("fade_out", True)),
                                key=f"fade_out_{job_id}_{idx}",
                            )

                            if st.button("⚡ Apply filter", key=f"apply_filter_{job_id}_{idx}"):
                                filter_values = {
                                    "brightness": brightness,
                                    "contrast": contrast,
                                    "saturation": saturation,
                                    "hue": hue,
                                    "sharpness": sharpness,
                                    "vignette": vignette,
                                    "fade_in": fade_in,
                                    "fade_out": fade_out,
                                }
                                with st.spinner("Applying filter..."):
                                    try:
                                        response = requests.post(
                                            f"{BACKEND_URL}/apply-filter/{job_id}/{filename}",
                                            json=filter_values,
                                            timeout=120,
                                        )
                                        if response.status_code == 200:
                                            result = response.json()
                                            filtered_name = result.get("filtered_filename")
                                            if filtered_name:
                                                st.session_state.filter_output_by_clip[f"{job_id}_{idx}"] = filtered_name
                                                st.success("Filtered clip ready")
                                        else:
                                            detail = response.json().get("detail", response.text)
                                            st.error(f"Filter application failed: {detail}")
                                    except Exception as exc:
                                        st.error(f"Filter request failed: {exc}")

                            filtered_name = st.session_state.filter_output_by_clip.get(f"{job_id}_{idx}")
                            if filtered_name:
                                st.write(f"Filtered clip: {filtered_name}")
                                if st.button("⬇ Download filtered clip", key=f"download_filtered_{job_id}_{idx}"):
                                    filtered_bytes = fetch_backend_bytes(
                                        f"{BACKEND_URL}/download-filtered/{job_id}/{filtered_name}",
                                        "Filtered download",
                                    )
                                    if filtered_bytes:
                                        st.download_button(
                                            "Download now",
                                            filtered_bytes,
                                            file_name=filtered_name,
                                            mime="video/mp4",
                                            key=f"download_filtered_button_{job_id}_{idx}",
                                        )

                        with c3:
                            preview_key = f"show_preview_{job_id}_{idx}"
                            if st.button("▶ Preview clip", key=f"preview_{job_id}_{idx}"):
                                st.session_state.show_preview_for_clip[preview_key] = not st.session_state.show_preview_for_clip.get(preview_key, False)
                            if st.session_state.show_preview_for_clip.get(preview_key):
                                st.video(f"{BACKEND_URL}/download/{job_id}/{filename}")
                                st.caption("Preview streamed from backend")

                        with st.expander("YouTube metadata", expanded=False):
                            if clip.get("title"):
                                st.write(f"**Title:** {clip['title']}")
                            if clip.get("description"):
                                st.write(f"**Description:** {clip['description']}")
                            if clip.get("hook"):
                                st.write(f"**Hook:** {clip['hook']}")
                            if clip.get("hashtags"):
                                tags = " ".join([f"#{tag}" for tag in clip["hashtags"]])
                                st.write(f"**Hashtags:** {tags}")
                                if st.button("Copy hashtags", key=f"copy_tags_{job_id}_{idx}"):
                                    st.session_state.copy_text = tags
                                    st.success("Hashtags copied to session state")

            shorts_clips = status_data.get("shorts_clips", [])
            if shorts_clips:
                st.subheader(f"Shorts clips ({len(shorts_clips)})")
                for idx, short in enumerate(shorts_clips, start=1):
                    with st.container():
                        st.write(f"**Short {idx}**")
                        st.write(f"Score: {short.get('score', 0)}/100")
                        filename = short.get("filename", "")
                        if st.button("⬇ Download shorts", key=f"download_shorts_{job_id}_{idx}"):
                            short_bytes = download_clip(job_id, filename, is_shorts=True)
                            if short_bytes:
                                st.download_button(
                                    "Download now",
                                    short_bytes,
                                    file_name=filename,
                                    mime="video/mp4",
                                    key=f"download_shorts_button_{job_id}_{idx}",
                                )

            if st.button("🗑️ Clean up and start a new job", use_container_width=True):
                cleanup_job(job_id)
                st.session_state.job_id = None
                safe_rerun()

            chapters = status_data.get("chapters", [])
            youtube_chapters = status_data.get("youtube_chapters", "")
            if chapters or youtube_chapters:
                st.divider()
                st.subheader("Detected chapters")
                for chapter in chapters:
                    ts = chapter.get("timestamp_str") or str(chapter.get("start", 0))
                    st.write(f"- {ts} {chapter.get('title', 'Chapter')}")
                if youtube_chapters:
                    st.text_area("YouTube chapters (copy-ready)", value=youtube_chapters, height=200)

        elif status in ["error", "failed"]:
            st.error("❌ An error occurred during processing.")
            st.code(status_data.get("error", "Unknown error"))
            if st.button("Start a new job", use_container_width=True):
                st.session_state.confirm_new_job = True
            # Allow retrying the failed job using the last uploaded file if available
            if st.session_state.get("last_upload"):
                if st.button("Retry with previous upload", use_container_width=True):
                    with st.spinner("Retrying with stored upload..."):
                        job_id_new = upload_video(
                            st.session_state.last_upload,
                            st.session_state.guidance,
                            st.session_state.generate_shorts,
                            st.session_state.language,
                        )
                        if job_id_new:
                            st.session_state.job_id = job_id_new
                            add_job_to_history(
                                job_id_new,
                                "Retry",
                                st.session_state.guidance,
                                st.session_state.language,
                                st.session_state.generate_shorts,
                            )
                            safe_rerun()
        else:
            st.info("Processing is ongoing. The page refreshes automatically.")
            time.sleep(POLL_INTERVAL_SECONDS)
            safe_rerun()

    render_footer()


if __name__ == "__main__":
    main()
