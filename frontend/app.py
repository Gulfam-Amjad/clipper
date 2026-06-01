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
STEP_ICONS = {
    "downloading":           "⬇️",
    "extracting_audio":      "🎵",
    "transcribing":          "📝",
    "analyzing":             "🧠",
    "cutting":               "✂️",
    "creating_shorts":       "📱",
    "generating_seo":        "🔍",
    "generating_thumbnails": "🖼️",
}

# Page configuration
st.set_page_config(
    page_title="VideoClipper 🎬",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
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
        "yt_connected": False,
        "yt_auth_url": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Initialize session state now that helper functions are defined
init_session_state()

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
        
        st.divider()
        st.markdown("### 📺 YouTube")

        try:
            yt_r = requests.get(f"{BACKEND_URL}/youtube-status", timeout=5)
            yt_connected = yt_r.json().get("connected", False)
        except:
            yt_connected = False

        st.session_state.yt_connected = yt_connected

        if yt_connected:
            st.success("✅ YouTube Connected")
            st.caption("Ready to upload clips directly")
        else:
            st.warning("⚠️ Not Connected")
            if st.button("🔗 Connect YouTube", key="connect_yt_btn"):
                try:
                    r = requests.get(f"{BACKEND_URL}/youtube-auth-url", timeout=5)
                    data = r.json()
                    if "auth_url" in data:
                        st.session_state.yt_auth_url = data["auth_url"]
                    else:
                        st.error(data.get("error", "Setup required"))
                        if "setup_guide" in data:
                            st.info(data["setup_guide"])
                except Exception as e:
                    st.error(f"Error: {e}")
            
            if st.session_state.get("yt_auth_url"):
                st.markdown(f"**[1. Click here to authorize]({st.session_state.yt_auth_url})**")
                code = st.text_input("2. Paste code here:", key="yt_code_input")
                if st.button("✅ Connect", key="yt_connect_confirm"):
                    if code:
                        try:
                            r = requests.post(f"{BACKEND_URL}/youtube-connect",
                                             json={"auth_code": code}, timeout=15)
                            if r.json().get("success"):
                                st.success("Connected!")
                                st.session_state.yt_auth_url = None
                                st.rerun()
                            else:
                                st.error("Failed — check the code")
                        except:
                            st.error("Connection error")


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
    st.markdown(
        '<div class="main-header"><h1>🎬 VideoClipper - AI-Powered Video Clip Generator</h1></div>',
        unsafe_allow_html=True,
    )

    backend_available = check_backend_health()
    if not backend_available:
        st.warning(
            f"Backend is offline at {BACKEND_URL}. Processing, preview, and downloads require the backend."
        )
        st.info("Start it with: cd backend && uvicorn main:app --reload")

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
                if video_file:
                    st.session_state.last_upload = {
                        "name": video_file.name,
                        "bytes": video_file.getvalue(),
                        "type": video_file.type,
                    }
            with right:
                st.markdown("#### Options")
                st.info("Set guidance and options in the sidebar.")
                if st.button("🚀 Start Processing", type="primary", disabled=not video_file):
                    job_id = upload_video(
                        video_file,
                        st.session_state.guidance,
                        st.session_state.generate_shorts,
                        st.session_state.language,
                    )
                    if job_id:
                        st.session_state.job_id = job_id
                        add_job_to_history(
                            job_id,
                            video_file.name,
                            st.session_state.guidance,
                            st.session_state.language,
                            st.session_state.generate_shorts,
                        )
                        safe_rerun()

        elif st.session_state.mode == "YouTube URL":
            left, right = st.columns([2, 1])
            with left:
                youtube_url = st.text_input("Enter a YouTube video URL")
                if youtube_url:
                    video_info = get_video_info(youtube_url)
                    if video_info:
                        st.markdown(f"**Title:** {video_info.get('title', 'N/A')}")
                        if "thumbnail" in video_info:
                            st.image(video_info["thumbnail"], width=320)
                    else:
                        st.warning("Could not fetch video info.")
            with right:
                st.markdown("#### Options")
                st.info("Set guidance and options in the sidebar.")
                if st.button("🚀 Start Processing", type="primary", disabled=not youtube_url):
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
                            youtube_url,
                            st.session_state.guidance,
                            st.session_state.language,
                            st.session_state.generate_shorts,
                        )
                        safe_rerun()
    else:
        job_id = st.session_state.job_id
        status_data = get_job_status(job_id)

        if status_data:
            status = status_data.get("status", "unknown")
            label, badge_class = render_status_badge(status)
            st.markdown(f'Job Status: <span class="status-badge {badge_class}">{label}</span>', unsafe_allow_html=True)

            if status not in ["done", "error", "failed"]:
                st.session_state.processing = True
                progress = status_data.get("progress", 0)
                
                icon = STEP_ICONS.get(status_data.get("status", ""), "⚙️")
                current_step = status_data.get("current_step", "Processing...")
                st.info(f"{icon} {current_step}")

                st.progress(progress / 100)
                if status_data.get("cache_used"):
                    st.caption("⚡ Using cached transcript — faster processing!")

                time.sleep(POLL_INTERVAL_SECONDS)
                safe_rerun()
            else:
                st.session_state.processing = False
                if status == "error":
                    st.error(f"Job failed: {status_data.get('error', 'Unknown error')}")
                else:
                    st.success("✅ Processing complete!")
                    results = status_data
                    clips = results.get("clips", [])
                    st.subheader(f"Generated Clips ({len(clips)})")

                    for i, clip in enumerate(clips):
                        col_thumb, col_info, col_dl = st.columns([1, 2, 1])

                        with col_thumb:
                            # Show professional thumbnail if available, fallback to basic
                            pro_thumb = clip.get("pro_thumbnail_path")
                            basic_thumb = clip.get("thumbnail_path")
                            
                            thumb_shown = False
                            
                            if pro_thumb:
                                fname = os.path.basename(pro_thumb)
                                try:
                                    r = requests.get(
                                        f"{BACKEND_URL}/download-thumbnail/{job_id}/{fname}", 
                                        timeout=10
                                    )
                                    if r.status_code == 200:
                                        st.image(r.content, use_column_width=True,
                                                caption="📸 AI Thumbnail")
                                        thumb_shown = True
                                except:
                                    pass
                            
                            if not thumb_shown and basic_thumb:
                                fname = os.path.basename(basic_thumb)
                                try:
                                    r = requests.get(
                                        f"{BACKEND_URL}/thumbnail/{job_id}/{fname}", 
                                        timeout=10
                                    )
                                    if r.status_code == 200:
                                        st.image(r.content, use_column_width=True)
                                        thumb_shown = True
                                except:
                                    pass
                            
                            if not thumb_shown:
                                st.markdown("🎬")
                                st.caption("No preview")

                        with col_info:
                            st.markdown(f"**{clip['label']}**")
                            st.caption(f"🕒 {clip['start']:.1f}s - {clip['end']:.1f}s")
                            st.caption(f"Quality Score: {clip.get('quality_score', 0):.1f}/100")

                            viral = clip.get("combined_viral_score", 0)
                            if viral:
                                v_emoji = "🔥" if viral >= 70 else "📈" if viral >= 40 else "📉"
                                st.caption(f"Viral Potential: {v_emoji} {viral}/100")
                                
                                llm_viral = clip.get("viral_llm", {})
                                pf = llm_viral.get("platform_fit", {})
                                if pf:
                                    c1, c2, c3 = st.columns(3)
                                    c1.metric("YT Shorts", f"{pf.get('youtube_shorts',0)}%")
                                    c2.metric("TikTok", f"{pf.get('tiktok',0)}%")
                                    c3.metric("Instagram", f"{pf.get('instagram',0)}%")
                                
                                tip = llm_viral.get("improvement", "")
                                if tip:
                                    st.caption(f"💡 Tip: {tip}")

                            with st.expander("🔍 Complete SEO Package", expanded=False):
    
                                # Title
                                if clip.get("title"):
                                    st.markdown("**📌 YouTube Title:**")
                                    st.code(clip["title"], language=None)
                                
                                # Description
                                if clip.get("description"):
                                    st.markdown("**📝 Description:**")
                                    st.text_area("desc", value=clip["description"], 
                                                 height=120, key=f"seo_desc_{i}",
                                                 label_visibility="collapsed")
                                
                                # Tags
                                if clip.get("tags"):
                                    st.markdown("**🏷 Tags:**")
                                    tags_str = ", ".join(clip["tags"])
                                    st.text_area("tags", value=tags_str, height=80,
                                                 key=f"seo_tags_{i}",
                                                 label_visibility="collapsed")
                                
                                # Hashtags
                                if clip.get("hashtags"):
                                    st.markdown("**# Hashtags:**")
                                    ht_str = " ".join(clip["hashtags"])
                                    st.code(ht_str, language=None)
                                
                                # Hook
                                if clip.get("hook"):
                                    st.markdown(f"**🎣 Hook:** *{clip['hook']}*")
                                
                                # SEO Score
                                if clip.get("seo_score"):
                                    score = clip["seo_score"]
                                    emoji = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"
                                    col_s1, col_s2 = st.columns([1, 2])
                                    col_s1.metric("SEO Score", f"{score}/100")
                                    col_s2.progress(score / 100)

                        with col_dl:
                            clip_filename = Path(clip["output_path"]).name
                            clip_data = download_clip(job_id, clip_filename)
                            if clip_data:
                                st.download_button(
                                    label="⬇️ Download Clip",
                                    data=clip_data,
                                    file_name=clip_filename,
                                    mime="video/mp4",
                                    key=f"dl_{i}",
                                )
                            
                            yt_connected = st.session_state.get("yt_connected", False)
    
                            if yt_connected:
                                st.markdown("---")
                                privacy_opt = st.selectbox(
                                    "Privacy", 
                                    ["private", "unlisted", "public"],
                                    key=f"yt_privacy_{i}",
                                    help="Private = only you can see"
                                )
                                
                                yt_url = clip.get("youtube_url")
                                if yt_url:
                                    st.success("✅ Uploaded!")
                                    st.markdown(f"[▶ View on YouTube]({yt_url})")
                                else:
                                    if st.button("📺 Upload to YouTube", 
                                                key=f"yt_upload_{i}"):
                                        with st.spinner("Uploading..."):
                                            try:
                                                r = requests.post(
                                                    f"{BACKEND_URL}/upload-to-youtube/{job_id}/{i}",
                                                    json={"privacy": privacy_opt},
                                                    timeout=300
                                                )
                                                if r.status_code == 200:
                                                    st.success(f"✅ Clip uploaded!")
                                                    # Refresh status to get the new URL
                                                    st.session_state.results = get_job_status(job_id)
                                                    st.rerun()
                                                else:
                                                    st.error(f"Upload failed: {r.text}")
                                            except Exception as e:
                                                st.error(f"Error: {str(e)[:100]}")

                        st.divider()

        if st.button("Process Another Video", key="process_another"):
            st.session_state.job_id = None
            safe_rerun()

    render_footer()


if __name__ == "__main__":
    main()
