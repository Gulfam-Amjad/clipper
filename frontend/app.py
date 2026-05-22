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

# Get backend URL from environment or use default
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Page configuration
st.set_page_config(
    page_title="VideoClipper 🎬",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

# Initialize session state
if "job_id" not in st.session_state:
    st.session_state.job_id = None
if "processing" not in st.session_state:
    st.session_state.processing = False
if "last_status_check" not in st.session_state:
    st.session_state.last_status_check = None


def check_backend_health():
    """Check if backend is running"""
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def upload_video(video_file, guidance, generate_shorts, language: str = "en"):
    """Upload and process a video file"""
    try:
        files = {"video": video_file}
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
            st.session_state.job_id = result["job_id"]
            st.success("✅ Video processing started!")
            return result["job_id"]
        else:
            try:
                error_detail = response.json().get("detail", "Unknown error")
            except:
                error_detail = response.text or f"HTTP {response.status_code}"
            st.error(f"❌ Failed to process video: {error_detail}")
            return None

    except requests.exceptions.Timeout:
        st.error("❌ Request timed out. Please try again.")
        return None
    except Exception as e:
        st.error(f"❌ Error uploading video: {str(e)}")
        return None


def process_youtube_url(youtube_url, guidance, generate_shorts, language: str = "en"):
    """Process a YouTube video"""
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
            st.session_state.job_id = result["job_id"]
            st.success("✅ YouTube video processing started!")
            return result["job_id"]
        else:
            try:
                error_detail = response.json().get("detail", "Unknown error")
            except:
                error_detail = response.text or f"HTTP {response.status_code}"
            st.error(f"❌ Failed to process YouTube URL: {error_detail}")
            return None

    except requests.exceptions.Timeout:
        st.error("❌ Request timed out. Please try again.")
        return None
    except Exception as e:
        st.error(f"❌ Error processing YouTube URL: {str(e)}")
        return None


def get_job_status(job_id):
    """Get the current status of a processing job"""
    try:
        response = requests.get(f"{BACKEND_URL}/status/{job_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        st.error(f"❌ Error fetching job status: {str(e)}")
        return None


def download_clip(job_id, filename, is_shorts=False):
    """Download a generated clip"""
    try:
        if is_shorts:
            url = f"{BACKEND_URL}/download-shorts/{job_id}/{filename}"
        else:
            url = f"{BACKEND_URL}/download/{job_id}/{filename}"

        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.content
        else:
            return None
    except Exception as e:
        st.error(f"❌ Error downloading clip: {str(e)}")
        return None


def cleanup_job(job_id):
    """Clean up a finished job"""
    try:
        response = requests.delete(f"{BACKEND_URL}/cleanup/{job_id}", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_video_info(youtube_url):
    """Get video info from YouTube URL"""
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


# Main application
def main():
    """Main Streamlit application"""

    # Header
    st.markdown(
        '<div class="main-header"><h1>🎬 VideoClipper - AI-Powered Video Clip Generator</h1></div>',
        unsafe_allow_html=True,
    )

    # Check backend health
    if not check_backend_health():
        st.error(
            "❌ Backend service is not available. Please make sure the backend is running at "
            f"{BACKEND_URL}"
        )
        st.info(
            "Start the backend with: `cd backend && python main.py`"
        )
        return

    # Sidebar
    with st.sidebar:
        st.title("Options")

        # Mode selection
        mode = st.radio(
            "Processing Mode",
            ["Upload Video", "YouTube URL"],
            help="Choose between uploading a local video or processing a YouTube video",
        )

        # Guidance text
        guidance = st.text_area(
            "Guidance (optional)",
            placeholder="Describe what kind of clips you want to extract (e.g., 'funny moments', 'educational content')",
            max_chars=500,
            help="Provide optional guidance to the AI for clip selection",
        )

        # Shorts mode
        generate_shorts = st.checkbox(
            "Generate YouTube Shorts (9:16)",
            value=False,
            help="Also create vertical format clips suitable for YouTube Shorts",
        )

        # Language selector (fetch from backend with graceful fallback)
        try:
            lang_response = requests.get(f"{BACKEND_URL}/languages", timeout=5)
            languages = lang_response.json() if lang_response.status_code == 200 else {"en": "English"}
        except Exception:
            languages = {"en": "English", "ur": "Urdu", "ar": "Arabic"}

        language = st.selectbox(
            "Video Language",
            options=list(languages.keys()),
            format_func=lambda x: languages.get(x, x),
            index=0,
        )

    # Main content area
    if st.session_state.job_id is None:
        # Initial upload interface
        st.subheader("Upload and Process Your Video")

        if mode == "Upload Video":
            col1, col2 = st.columns([2, 1])

            with col1:
                video_file = st.file_uploader(
                    "Choose a video file",
                    type=["mp4", "mov", "avi", "mkv"],
                    help="Maximum file size: 500MB",
                )

            with col2:
                if st.button(
                    "🚀 Process Video",
                    use_container_width=True,
                    type="primary",
                ):
                    if video_file is not None:
                        with st.spinner("Uploading video..."):
                            job_id = upload_video(
                                video_file, guidance, generate_shorts, language
                            )
                            if job_id:
                                st.rerun()
                    else:
                        st.warning("Please select a video file first")

            st.info(
                "💡 Supported formats: MP4, MOV, AVI, MKV (max 500MB)"
            )

        else:  # YouTube URL mode
            col1, col2 = st.columns([2, 1])

            with col1:
                youtube_url = st.text_input(
                    "YouTube URL",
                    placeholder="https://www.youtube.com/watch?v=...",
                    help="Paste a valid YouTube URL",
                )

            with col2:
                if st.button(
                    "🚀 Process URL",
                    use_container_width=True,
                    type="primary",
                ):
                    if youtube_url:
                        with st.spinner("Validating YouTube URL..."):
                            job_id = process_youtube_url(
                                youtube_url, guidance, generate_shorts, language
                            )
                            if job_id:
                                st.rerun()
                    else:
                        st.warning("Please enter a YouTube URL first")

            if youtube_url:
                # Show video info if URL is provided
                with st.spinner("Fetching video information..."):
                    info = get_video_info(youtube_url)
                    if info:
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Title", info.get("title", "N/A")[:30] + "...")
                        with col2:
                            duration = info.get("duration", 0)
                            minutes = duration // 60
                            st.metric("Duration", f"{minutes} min")
                        with col3:
                            st.metric(
                                "Channel",
                                info.get("uploader", "N/A")[:20] + "...",
                            )

    else:
        # Status tracking and results
        job_id = st.session_state.job_id

        # Header with job ID
        st.subheader(f"Processing Job: {job_id[:8]}...")

        # Status refresh button
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("🔄 Refresh Status", use_container_width=True):
                st.rerun()

        with col2:
            if st.button("🏠 New Job", use_container_width=True):
                st.session_state.job_id = None
                cleanup_job(job_id)
                st.rerun()

        # Get current status
        with st.spinner("Fetching job status..."):
            status_data = get_job_status(job_id)

        if status_data is None:
            st.error("❌ Could not fetch job status. Job may have expired.")
            if st.button("Start New Job"):
                st.session_state.job_id = None
                st.rerun()
            return

        # Display status
        status = status_data.get("status", "unknown")
        progress = status_data.get("progress", 0)
        message = status_data.get("message", "Processing...")

        # Status badge
        if status == "done":
            status_color = "status-done"
            status_text = "✅ COMPLETED"
        elif status in ["error", "failed"]:
            status_color = "status-error"
            status_text = "❌ ERROR"
        else:
            status_color = "status-processing"
            status_text = f"⏳ {status.upper()}"

        st.markdown(
            f'<p style="font-size: 18px;"><span class="status-badge {status_color}">{status_text}</span></p>',
            unsafe_allow_html=True,
        )

        # Progress bar
        st.progress(min(progress / 100.0, 1.0))
        st.write(f"**Progress:** {progress}% - {message}")

        # Display status details
        st.divider()

        if status == "done":
            st.success("✅ Processing completed successfully!")

            # Display clips
            clips = status_data.get("clips", [])
            if clips:
                st.subheader(f"Generated Clips ({len(clips)})")

                for idx, clip in enumerate(clips, 1):
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 1, 1])

                        with col1:
                            title = clip.get("title", f"Clip {idx}")
                            start_time = clip.get("start", 0)
                            end_time = clip.get("end", 0)
                            duration = end_time - start_time
                            st.write(
                                f"**{title}**  \n"
                                f"⏱️ {start_time:.1f}s - {end_time:.1f}s ({duration:.1f}s)  \n"
                                f"Score: {'⭐' * min(int(clip.get('score', 0) / 20), 5)}"
                            )

                            # Viral score display
                            viral_score = clip.get("combined_viral_score", 0)
                            if viral_score:
                                viral_color = "🔥" if viral_score >= 70 else "📈" if viral_score >= 40 else "📉"
                                st.caption(f"Viral Potential: {viral_color} {viral_score}/100")

                                # Platform fit breakdown
                                llm_data = clip.get("viral_llm", {}) or {}
                                platform_fit = llm_data.get("platform_fit", {}) or {}
                                if platform_fit:
                                    pcols = st.columns(3)
                                    pcols[0].metric("YouTube", f"{platform_fit.get('youtube_shorts',0)}%")
                                    pcols[1].metric("TikTok", f"{platform_fit.get('tiktok',0)}%")
                                    pcols[2].metric("Instagram", f"{platform_fit.get('instagram',0)}%")

                                # Improvement suggestion
                                improvement = llm_data.get("improvement", "")
                                if improvement:
                                    st.caption(f"💡 {improvement}")

                        with col2:
                            filename = clip.get("filename", "")
                            if st.button(
                                "📥 Download",
                                key=f"clip_{idx}",
                                use_container_width=True,
                            ):
                                video_data = download_clip(job_id, filename)
                                if video_data:
                                    st.download_button(
                                        label="📥 Click to Download",
                                        data=video_data,
                                        file_name=filename,
                                        mime="video/mp4",
                                        key=f"download_{idx}",
                                    )

                        with col3:
                            # Preview button toggles an in-page preview
                            if st.button("👁 Preview", key=f"preview_btn_{idx}", use_container_width=True):
                                st.session_state[f"show_preview_{idx}"] = not st.session_state.get(f"show_preview_{idx}", False)

                            if st.session_state.get(f"show_preview_{idx}", False):
                                with st.spinner("Loading preview..."):
                                    try:
                                        r = requests.get(
                                            f"{BACKEND_URL}/download/{job_id}/{filename}",
                                            timeout=60,
                                        )
                                        if r.status_code == 200:
                                            st.video(r.content)
                                        else:
                                            st.warning("Preview unavailable")
                                    except requests.exceptions.RequestException:
                                        st.warning("Could not load preview")

                        # YouTube metadata expander
                        with st.expander("📋 YouTube Metadata", expanded=False):
                            if clip.get("title"):
                                st.markdown(f"**Title:** {clip['title']}")
                            if clip.get("description"):
                                st.markdown(f"**Description:** {clip['description']}")
                            if clip.get("hook"):
                                st.markdown(f"**Hook:** *{clip['hook']}*")
                            if clip.get("hashtags"):
                                tags = " ".join([f"#{t}" for t in clip["hashtags"]])
                                st.markdown(f"**Hashtags:** {tags}")
                                if st.button("📋 Copy Hashtags", key=f"copy_tags_{idx}"):
                                    st.session_state.update({"copied": tags})

            # Display Shorts clips if available
            shorts_clips = status_data.get("shorts_clips", [])
            if shorts_clips:
                st.subheader(f"YouTube Shorts ({len(shorts_clips)})")

                cols = st.columns(2)
                for idx, short in enumerate(shorts_clips):
                    with cols[idx % 2]:
                        with st.container(border=True):
                            filename = short.get("filename", "")
                            st.write(
                                f"**Shorts {idx + 1}**  \n"
                                f"Score: {'⭐' * min(int(short.get('score', 0) / 20), 5)}"
                            )

                            if st.button(
                                "📥 Download",
                                key=f"shorts_{idx}",
                                use_container_width=True,
                            ):
                                video_data = download_clip(
                                    job_id, filename, is_shorts=True
                                )
                                if video_data:
                                    st.download_button(
                                        label="📥 Click to Download",
                                        data=video_data,
                                        file_name=filename,
                                        mime="video/mp4",
                                        key=f"download_shorts_{idx}",
                                    )

            # Cleanup button
            st.divider()
            if st.button("🗑️ Clean Up & Start New Job", use_container_width=True):
                cleanup_job(job_id)
                st.session_state.job_id = None
                st.rerun()

            # Chapters display (from status)
            chapters = status_data.get("chapters", [])
            youtube_chapters = status_data.get("youtube_chapters", "")
            if chapters or youtube_chapters:
                st.divider()
                st.subheader("Detected Chapters")
                if chapters:
                    for ch in chapters:
                        ts = ch.get("timestamp_str") or f"{ch.get('start',0)}"
                        st.write(f"- {ts} {ch.get('title','Chapter')}")

                if youtube_chapters:
                    st.text_area("YouTube Chapters (copy-ready)", value=youtube_chapters, height=200)

        elif status in ["error", "failed"]:
            st.error("❌ An error occurred during processing")
            error_msg = status_data.get("error", "Unknown error")
            st.code(error_msg, language="text")

            if st.button("🔄 Try Again", use_container_width=True):
                cleanup_job(job_id)
                st.session_state.job_id = None
                st.rerun()

        else:
            # Still processing
            st.info(
                "Processing is ongoing. The page will automatically refresh every 3 seconds."
            )

            # Auto-refresh every 3 seconds
            import time
            time.sleep(3)
            st.rerun()

    # Footer
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


if __name__ == "__main__":
    main()
