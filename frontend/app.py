import requests
import streamlit as st

BACKEND_URL = "http://localhost:8000"

st.set_page_config(
    page_title="VideoClipper AI",
    page_icon="🎬",
    layout="wide",
)

DEFAULTS = {
    "num_clips": 5,
    "min_length": 20,
    "max_length": 150,
    "shorts_format": True,
    "burn_subtitles": True,
    "normalize_audio": True,
    "visual_cleanup": False,
    "cleanup_position": "top_left",
    "add_music": False,
    "music_volume": 0.12,
}


def init_session_state() -> None:
    defaults = {
        "step": 1,
        "job_id": None,
        "filename": None,
        "file_path": None,
        "duration": 0.0,
        "transcript": None,
        "segments": [],
        "words": [],
        "transcript_data": None,
        "clips": [],
        "clip_selections": {},
        "processed_clips": [],
        "music_path": None,
        "music_filename": None,
        **DEFAULTS,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_mmss(seconds: float) -> str:
    total = int(seconds)
    minutes = total // 60
    secs = total % 60
    return f"{minutes:02d}:{secs:02d}"


def api_post(endpoint: str, json_data: dict | None = None, files=None):
    url = f"{BACKEND_URL}{endpoint}"
    if files:
        return requests.post(url, files=files, timeout=600)
    return requests.post(url, json=json_data, timeout=600)


def reset_app() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def upload_file(file_obj) -> dict:
    files = {"file": (file_obj.name, file_obj.getvalue(), file_obj.type)}
    resp = api_post("/upload", files=files)
    if resp.status_code != 200:
        raise RuntimeError(resp.text)
    return resp.json()


def transcribe_current_video() -> None:
    resp = api_post(
        "/transcribe",
        {
            "job_id": st.session_state.job_id,
            "file_path": st.session_state.file_path,
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(resp.text)
    data = resp.json()
    st.session_state.transcript = data["transcript"]
    st.session_state.segments = data["segments"]
    st.session_state.words = data["words"]
    st.session_state.transcript_data = data.get(
        "transcript_data",
        {
            "full_text": data["transcript"],
            "segments": data["segments"],
            "words": data["words"],
        },
    )


def select_best_clips() -> None:
    resp = api_post(
        "/select-clips",
        {
            "job_id": st.session_state.job_id,
            "transcript_data": st.session_state.transcript_data,
            "video_duration": st.session_state.duration,
            "num_clips": st.session_state.num_clips,
            "min_length": st.session_state.min_length,
            "max_length": st.session_state.max_length,
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(resp.text)

    st.session_state.clips = resp.json()["clips"]
    st.session_state.clip_selections = {}
    for clip in st.session_state.clips:
        num = clip["clip_number"]
        st.session_state.clip_selections[num] = {
            "include": True,
            "start_time": clip["start_time"],
            "end_time": clip["end_time"],
        }


def build_clips_payload() -> list[dict]:
    clips_payload = []
    for clip in st.session_state.clips:
        num = clip["clip_number"]
        sel = st.session_state.clip_selections.get(num, {})
        clips_payload.append(
            {
                "clip_number": num,
                "start_time": sel.get("start_time", clip["start_time"]),
                "end_time": sel.get("end_time", clip["end_time"]),
                "title": clip["title"],
                "reason": clip.get("reason", ""),
                "description": clip.get("description", ""),
                "hashtags": clip.get("hashtags", []),
                "virality_score": clip.get("virality_score", 60),
                "hook_score": clip.get("hook_score", 60),
                "content_score": clip.get("content_score", 60),
                "include": sel.get("include", True),
            }
        )
    return clips_payload


def process_selected_clips() -> None:
    resp = api_post(
        "/process-clips",
        {
            "job_id": st.session_state.job_id,
            "file_path": st.session_state.file_path,
            "clips": build_clips_payload(),
            "transcript_data": st.session_state.transcript_data,
            "options": {
                "shorts_format": st.session_state.shorts_format,
                "burn_subtitles": st.session_state.burn_subtitles,
                "add_music": st.session_state.add_music,
                "normalize_audio": st.session_state.normalize_audio,
                "visual_cleanup": st.session_state.visual_cleanup,
                "cleanup_position": st.session_state.cleanup_position,
                "music_volume": st.session_state.music_volume,
                "music_path": st.session_state.music_path,
            },
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(resp.text)
    st.session_state.processed_clips = resp.json()["processed_clips"]


def process_fast_downloads() -> None:
    """Create simple downloadable clips only. No heavy edit stack."""
    resp = api_post(
        "/process-clips",
        {
            "job_id": st.session_state.job_id,
            "file_path": st.session_state.file_path,
            "clips": build_clips_payload(),
            "transcript_data": st.session_state.transcript_data,
            "options": {
                "shorts_format": False,
                "burn_subtitles": False,
                "add_music": False,
                "normalize_audio": False,
                "visual_cleanup": False,
            },
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(resp.text)
    st.session_state.processed_clips = resp.json()["processed_clips"]


def run_auto_pipeline(video_file, music_file=None) -> None:
    status = st.status("Creating your clips...", expanded=True)
    try:
        status.write("Uploading video")
        uploaded_video = upload_file(video_file)
        st.session_state.job_id = uploaded_video["job_id"]
        st.session_state.filename = uploaded_video["filename"]
        st.session_state.file_path = uploaded_video["file_path"]
        st.session_state.duration = uploaded_video["duration"]

        if music_file is not None:
            status.write("Uploading background music")
            uploaded_music = upload_file(music_file)
            st.session_state.music_path = uploaded_music["file_path"]
            st.session_state.music_filename = uploaded_music["filename"]
            st.session_state.add_music = True

        status.write("Transcribing video")
        transcribe_current_video()

        status.write("Finding complete, viral-worthy moments")
        select_best_clips()

        status.update(
            label="Done — clip ideas are ready below",
            state="complete",
            expanded=False,
        )
    except requests.exceptions.ConnectionError as exc:
        status.update(label="Backend is not running", state="error")
        raise RuntimeError("Start backend with: uvicorn backend.main:app --reload --port 8000") from exc
    except Exception:
        status.update(label="Clip creation failed", state="error")
        raise


init_session_state()

st.title("VideoClipper AI")
st.caption("Upload once. Review ranked clip ideas first. Download fast cuts or render polished edits when ready.")

with st.sidebar:
    st.header("Clip Strategy")
    st.session_state.num_clips = st.slider(
        "Clips to create", 2, 8, st.session_state.num_clips
    )
    st.session_state.min_length = st.slider(
        "Minimum clip length", 10, 90, st.session_state.min_length, help="The AI can go longer when the conversation needs it."
    )
    st.session_state.max_length = st.slider(
        "Soft maximum length", 60, 240, st.session_state.max_length, help="Not a fixed clip size — just a guide."
    )

    st.header("Edit Style")
    st.session_state.shorts_format = st.toggle(
        "Vertical 9:16 with blur fill", value=st.session_state.shorts_format
    )
    st.session_state.burn_subtitles = st.toggle(
        "Animated captions", value=st.session_state.burn_subtitles
    )
    st.session_state.normalize_audio = st.toggle(
        "Normalize audio", value=st.session_state.normalize_audio
    )
    st.session_state.visual_cleanup = st.toggle(
        "Mask corner logo/name", value=st.session_state.visual_cleanup
    )
    if st.session_state.visual_cleanup:
        st.session_state.cleanup_position = st.selectbox(
            "Mask position",
            ["top_left", "top_right", "bottom_left", "bottom_right"],
            index=["top_left", "top_right", "bottom_left", "bottom_right"].index(
                st.session_state.cleanup_position
            ),
        )

    st.header("Music")
    st.session_state.add_music = st.toggle(
        "Use uploaded background music", value=st.session_state.add_music
    )
    st.session_state.music_volume = st.slider(
        "Music volume", 0.02, 0.30, st.session_state.music_volume, step=0.01
    )
    st.caption("Copyright note: masking/cropping does not make third-party content safe to monetize. Use your own or licensed content.")


left, right = st.columns([0.82, 1.18], vertical_alignment="top")

with left:
    st.subheader("Create Clips")
    uploaded = st.file_uploader(
        "Drop your long video",
        type=["mp4", "mov", "mkv", "avi"],
        help="For a 15-minute video, try 4–5 clips with a 20s–150s range.",
    )
    music_file = None
    if st.session_state.add_music:
        music_file = st.file_uploader(
            "Optional background music",
            type=["mp3", "wav", "m4a"],
            help="Funk/lofi/beat music will be mixed softly behind the original voice.",
        )

    if uploaded and st.button("Create Ranked Clips", type="primary", use_container_width=True):
        try:
            run_auto_pipeline(uploaded, music_file)
            st.rerun()
        except Exception as exc:
            st.error(f"Failed: {exc}")

    if st.button("Start Over", use_container_width=True):
        reset_app()

with right:
    st.subheader("Project Status")
    metrics = st.columns(4)
    metrics[0].metric("Video", st.session_state.filename or "Not uploaded")
    metrics[1].metric("Duration", format_duration(st.session_state.duration))
    metrics[2].metric("Ideas", len(st.session_state.clips))
    metrics[3].metric("Rendered", len(st.session_state.processed_clips))

    if st.session_state.transcript:
        with st.expander("Transcript", expanded=False):
            st.text(st.session_state.transcript[:8000])

    if st.session_state.clips and not st.session_state.processed_clips:
        st.info("Clip ideas are ready. Preview the source timestamps below, then create fast downloads or polished renders.")

if st.session_state.clips:
    st.markdown("---")
    st.subheader("Ranked Clip Ideas")
    source_url = None
    if st.session_state.filename:
        source_url = f"{BACKEND_URL}/preview-upload/{st.session_state.filename}"
    for clip in st.session_state.clips:
        num = clip["clip_number"]
        sel = st.session_state.clip_selections.get(num, {})
        with st.container(border=True):
            top = st.columns([0.62, 0.38])
            with top[0]:
                st.markdown(f"### #{num} {clip['title']}")
                st.caption(clip.get("reason", ""))
            with top[1]:
                c1, c2, c3 = st.columns(3)
                c1.metric("Viral", f"{clip.get('virality_score', 60)}/100")
                c2.metric("Hook", f"{clip.get('hook_score', 60)}/100")
                c3.metric("Content", f"{clip.get('content_score', 60)}/100")

            if clip.get("description"):
                st.write(clip["description"])
            if clip.get("hashtags"):
                st.markdown(" ".join(clip["hashtags"]))

            start_preview = int(sel.get("start_time", clip["start_time"]))
            end_preview = sel.get("end_time", clip["end_time"])
            if source_url:
                with st.expander(
                    f"Preview source from {format_mmss(start_preview)} to {format_mmss(end_preview)}",
                    expanded=False,
                ):
                    st.video(source_url, start_time=start_preview)
                    st.caption("Browser preview starts at the clip start. Stop playback near the shown end time.")

            a, b, c = st.columns([0.2, 0.4, 0.4])
            with a:
                include = st.checkbox(
                    "Render", value=sel.get("include", True), key=f"include_{num}"
                )
            with b:
                start = st.number_input(
                    "Start (seconds)",
                    min_value=0.0,
                    max_value=float(st.session_state.duration),
                    value=float(sel.get("start_time", clip["start_time"])),
                    step=0.5,
                    key=f"start_{num}",
                )
            with c:
                end = st.number_input(
                    "End (seconds)",
                    min_value=0.0,
                    max_value=float(st.session_state.duration),
                    value=float(sel.get("end_time", clip["end_time"])),
                    step=0.5,
                    key=f"end_{num}",
                )
            st.session_state.clip_selections[num] = {
                "include": include,
                "start_time": start,
                "end_time": end,
            }

    action_cols = st.columns(3)
    if action_cols[0].button("Regenerate Ideas", use_container_width=True):
        try:
            with st.spinner("Finding better clips..."):
                select_best_clips()
            st.rerun()
        except Exception as exc:
            st.error(f"Clip selection failed: {exc}")
    if action_cols[1].button("Create Download Files Only", type="primary", use_container_width=True):
        try:
            with st.spinner("Creating fast downloadable cuts..."):
                process_fast_downloads()
            st.rerun()
        except Exception as exc:
            st.error(f"Fast download creation failed: {exc}")
    if action_cols[2].button("Render Polished Edits", use_container_width=True):
        try:
            with st.spinner("Rendering polished clips... this is slower."):
                process_selected_clips()
            st.rerun()
        except Exception as exc:
            st.error(f"Processing failed: {exc}")

if st.session_state.processed_clips:
    st.markdown("---")
    st.subheader("Finished Clips")
    clip_paths = []
    for clip in st.session_state.processed_clips:
        filename = clip["filename"]
        clip_paths.append(clip["output_path"])
        download_url = f"{BACKEND_URL}/download/{filename}"
        with st.container(border=True):
            header = (
                f"### #{clip['clip_number']} {clip['title']} "
                f"({clip.get('virality_score', 60)}/100)"
            )
            st.markdown(header)
            try:
                video_resp = requests.get(download_url, timeout=120)
                if video_resp.status_code == 200:
                    col_vid, col_meta = st.columns([1, 1])
                    with col_vid:
                        st.video(video_resp.content)
                        st.download_button(
                            label=f"Download {filename}",
                            data=video_resp.content,
                            file_name=filename,
                            mime="video/mp4",
                            key=f"dl_{clip['clip_number']}",
                            use_container_width=True,
                        )
                    with col_meta:
                        caption_lines = [clip["title"]]
                        if clip.get("description"):
                            caption_lines.extend(["", clip["description"]])
                        if clip.get("hashtags"):
                            caption_lines.extend(["", " ".join(clip["hashtags"])])
                        st.markdown("**Copy-paste upload caption**")
                        st.code("\n".join(caption_lines), language=None)
                        score_cols = st.columns(3)
                        score_cols[0].metric("Viral", f"{clip.get('virality_score', 60)}/100")
                        score_cols[1].metric("Hook", f"{clip.get('hook_score', 60)}/100")
                        score_cols[2].metric("Content", f"{clip.get('content_score', 60)}/100")
                else:
                    st.warning("Preview unavailable — use download button below.")
            except Exception:
                st.warning("Preview unavailable — try downloading from the backend URL.")

    if st.button("Download All as ZIP", use_container_width=True):
        try:
            zip_resp = api_post(
                "/download-zip",
                {"job_id": st.session_state.job_id, "clip_paths": clip_paths},
            )
            if zip_resp.status_code == 200:
                st.download_button(
                    label="Save ZIP file",
                    data=zip_resp.content,
                    file_name=f"{st.session_state.job_id}_clips.zip",
                    mime="application/zip",
                    key="zip_download",
                    use_container_width=True,
                )
            else:
                st.error(f"ZIP creation failed: {zip_resp.text}")
        except Exception as exc:
            st.error(f"ZIP download error: {exc}")

st.stop()

# ── Step 1: Upload ──────────────────────────────────────────────────────────
if st.session_state.step == 1:
    uploaded = st.file_uploader(
        "Upload a video",
        type=["mp4", "mov", "mkv", "avi"],
        help="Supported formats: MP4, MOV, MKV, AVI",
    )

    if uploaded and st.button("Upload Video", type="primary"):
        try:
            with st.spinner("Uploading video..."):
                files = {
                    "file": (uploaded.name, uploaded.getvalue(), uploaded.type)
                }
                resp = api_post("/upload", files=files)
                if resp.status_code != 200:
                    st.error(f"Upload failed: {resp.text}")
                else:
                    data = resp.json()
                    st.session_state.job_id = data["job_id"]
                    st.session_state.filename = data["filename"]
                    st.session_state.file_path = data["file_path"]
                    st.session_state.duration = data["duration"]
                    st.success(f"Uploaded **{uploaded.name}** successfully!")
        except requests.exceptions.ConnectionError:
            st.error(
                "Cannot connect to backend. Start it with: "
                "`uvicorn backend.main:app --reload --port 8000`"
            )
        except Exception as exc:
            st.error(f"Upload error: {exc}")

    if st.session_state.job_id:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("File", st.session_state.filename)
        with col2:
            st.metric("Duration", format_duration(st.session_state.duration))

        if st.button("Proceed to Transcription →", type="primary"):
            st.session_state.step = 2
            st.rerun()

# ── Step 2: Transcribe ──────────────────────────────────────────────────────
elif st.session_state.step == 2:
    st.subheader("Step 2 — Transcribe")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Video", st.session_state.filename)
    with col2:
        st.metric("Duration", format_duration(st.session_state.duration))

    if st.button("🎙️ Transcribe Video", type="primary"):
        try:
            with st.spinner("Transcribing... this may take a minute"):
                resp = api_post(
                    "/transcribe",
                    {
                        "job_id": st.session_state.job_id,
                        "file_path": st.session_state.file_path,
                    },
                )
                if resp.status_code != 200:
                    st.error(f"Transcription failed: {resp.text}")
                else:
                    data = resp.json()
                    st.session_state.transcript = data["transcript"]
                    st.session_state.segments = data["segments"]
                    st.session_state.words = data["words"]
                    st.session_state.transcript_data = data.get(
                        "transcript_data",
                        {
                            "full_text": data["transcript"],
                            "segments": data["segments"],
                            "words": data["words"],
                        },
                    )
                    st.success("Transcription complete!")
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to backend. Is it running on port 8000?")
        except Exception as exc:
            st.error(f"Transcription error: {exc}")

    if st.session_state.transcript:
        with st.expander("Full Transcript", expanded=False):
            st.text(st.session_state.transcript)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Segments", len(st.session_state.segments))
        with col2:
            st.metric("Words", len(st.session_state.words))

        if st.button("Proceed to Clip Selection →", type="primary"):
            st.session_state.step = 3
            st.rerun()

    if st.button("← Back to Upload"):
        st.session_state.step = 1
        st.rerun()

# ── Step 3: Review Clips ────────────────────────────────────────────────────
elif st.session_state.step == 3:
    st.subheader("Step 3 — Review Clips")

    with st.container(border=True):
        st.markdown("**Clip settings**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state.num_clips = st.slider(
                "How many clips", 1, 10, st.session_state.num_clips
            )
        with c2:
            st.session_state.min_length = st.slider(
                "Min length (s)", 5, 90, st.session_state.min_length
            )
        with c3:
            st.session_state.max_length = st.slider(
                "Max length (s)", 15, 180, st.session_state.max_length
            )

        btn_label = "🔁 Regenerate Clips" if st.session_state.clips else "🤖 Find Best Clips"
        if st.button(btn_label, type="primary"):
            if st.session_state.min_length >= st.session_state.max_length:
                st.warning("Min length must be less than max length.")
            else:
                try:
                    with st.spinner("🤖 Analyzing transcript and finding viral moments..."):
                        resp = api_post(
                            "/select-clips",
                            {
                                "job_id": st.session_state.job_id,
                                "transcript_data": st.session_state.transcript_data,
                                "video_duration": st.session_state.duration,
                                "num_clips": st.session_state.num_clips,
                                "min_length": st.session_state.min_length,
                                "max_length": st.session_state.max_length,
                            },
                        )
                        if resp.status_code != 200:
                            st.error(f"Clip selection failed: {resp.text}")
                        else:
                            st.session_state.clips = resp.json()["clips"]
                            st.session_state.clip_selections = {}
                            for clip in st.session_state.clips:
                                num = clip["clip_number"]
                                st.session_state.clip_selections[num] = {
                                    "include": True,
                                    "start_time": clip["start_time"],
                                    "end_time": clip["end_time"],
                                }
                            st.rerun()
                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to backend. Is it running on port 8000?")
                except Exception as exc:
                    st.error(f"Clip selection error: {exc}")

    if st.session_state.clips:
        for clip in st.session_state.clips:
            num = clip["clip_number"]
            sel = st.session_state.clip_selections.get(num, {})

            with st.container(border=True):
                score = clip.get("virality_score")
                title_line = f"### Clip {num}: {clip['title']}"
                if score:
                    title_line += f"  🔥 {score}/10"
                st.markdown(title_line)
                st.markdown(
                    f"**{format_mmss(sel.get('start_time', clip['start_time']))}** → "
                    f"**{format_mmss(sel.get('end_time', clip['end_time']))}**"
                )
                if clip.get("reason"):
                    st.markdown(f"*{clip.get('reason', '')}*")
                if clip.get("description"):
                    st.caption(clip["description"])
                if clip.get("hashtags"):
                    st.markdown(" ".join(clip["hashtags"]))

                include = st.checkbox(
                    "Include this clip",
                    value=sel.get("include", True),
                    key=f"include_{num}",
                )
                col1, col2 = st.columns(2)
                with col1:
                    start = st.number_input(
                        "Adjust Start (seconds)",
                        min_value=0.0,
                        max_value=float(st.session_state.duration),
                        value=float(sel.get("start_time", clip["start_time"])),
                        step=0.5,
                        key=f"start_{num}",
                    )
                with col2:
                    end = st.number_input(
                        "Adjust End (seconds)",
                        min_value=0.0,
                        max_value=float(st.session_state.duration),
                        value=float(sel.get("end_time", clip["end_time"])),
                        step=0.5,
                        key=f"end_{num}",
                    )

                st.session_state.clip_selections[num] = {
                    "include": include,
                    "start_time": start,
                    "end_time": end,
                }

        selected_count = sum(
            1 for s in st.session_state.clip_selections.values() if s["include"]
        )
        st.metric("Clips Selected", selected_count)

        col_back, col_next = st.columns(2)
        with col_back:
            if st.button("← Back to Transcribe"):
                st.session_state.clips = []
                st.session_state.clip_selections = {}
                st.session_state.step = 2
                st.rerun()
        with col_next:
            if st.button(
                "Proceed to Export →",
                type="primary",
                disabled=selected_count == 0,
            ):
                st.session_state.step = 4
                st.rerun()

# ── Step 4: Export ──────────────────────────────────────────────────────────
elif st.session_state.step == 4:
    st.subheader("Step 4 — Export Options")

    shorts_format = st.toggle(
        "📱 Convert to vertical 9:16 (Shorts / TikTok / Reels)", value=True
    )
    burn_subtitles = st.toggle(
        "💬 Burn animated captions into clips", value=True
    )
    normalize = st.toggle("🔊 Normalize audio loudness", value=True)
    add_music = st.toggle("🎵 Add Background Music", value=False)

    music_path = st.session_state.music_path
    if add_music:
        music_file = st.file_uploader("Upload background music (MP3)", type=["mp3"])
        if music_file and st.button("Upload Music"):
            try:
                with st.spinner("Uploading music..."):
                    files = {
                        "file": (music_file.name, music_file.getvalue(), music_file.type)
                    }
                    resp = api_post("/upload", files=files)
                    if resp.status_code != 200:
                        st.error(f"Music upload failed: {resp.text}")
                    else:
                        data = resp.json()
                        st.session_state.music_path = data["file_path"]
                        st.session_state.music_filename = data["filename"]
                        st.success(f"Music uploaded: {data['filename']}")
            except Exception as exc:
                st.error(f"Music upload error: {exc}")

        if st.session_state.music_filename:
            st.info(f"Using music: {st.session_state.music_filename}")

    if st.button("🚀 Process & Export Clips", type="primary"):
        try:
            clips_payload = []
            for clip in st.session_state.clips:
                num = clip["clip_number"]
                sel = st.session_state.clip_selections.get(num, {})
                clips_payload.append(
                    {
                        "clip_number": num,
                        "start_time": sel.get("start_time", clip["start_time"]),
                        "end_time": sel.get("end_time", clip["end_time"]),
                        "title": clip["title"],
                        "reason": clip.get("reason", ""),
                        "description": clip.get("description", ""),
                        "hashtags": clip.get("hashtags", []),
                        "virality_score": clip.get("virality_score", 5),
                        "include": sel.get("include", True),
                    }
                )

            included = [c for c in clips_payload if c["include"]]
            with st.spinner(
                f"Cutting and rendering {len(included)} clip(s)... "
                "this can take a few minutes for longer videos."
            ):
                resp = api_post(
                    "/process-clips",
                    {
                        "job_id": st.session_state.job_id,
                        "file_path": st.session_state.file_path,
                        "clips": clips_payload,
                        "transcript_data": st.session_state.transcript_data,
                        "options": {
                            "shorts_format": shorts_format,
                            "burn_subtitles": burn_subtitles,
                            "add_music": add_music,
                            "normalize_audio": normalize,
                            "music_path": st.session_state.music_path,
                        },
                    },
                )

            if resp.status_code != 200:
                st.error(f"Processing failed: {resp.text}")
            else:
                st.session_state.processed_clips = resp.json()["processed_clips"]
                st.success("Clips ready for download!")
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to backend. Is it running on port 8000?")
        except Exception as exc:
            st.error(f"Processing error: {exc}")

    if st.session_state.processed_clips:
        st.markdown("---")
        st.subheader("Your Clips")

        clip_paths = []
        for clip in st.session_state.processed_clips:
            filename = clip["filename"]
            clip_paths.append(clip["output_path"])
            download_url = f"{BACKEND_URL}/download/{filename}"

            with st.container(border=True):
                score = clip.get("virality_score")
                header = f"**Clip {clip['clip_number']}: {clip['title']}**"
                if score:
                    header += f"  🔥 {score}/10"
                st.markdown(header)
                try:
                    video_resp = requests.get(download_url, timeout=120)
                    if video_resp.status_code == 200:
                        col_vid, col_meta = st.columns([1, 1])
                        with col_vid:
                            st.video(video_resp.content)
                            st.download_button(
                                label=f"⬇️ Download {filename}",
                                data=video_resp.content,
                                file_name=filename,
                                mime="video/mp4",
                                key=f"dl_{clip['clip_number']}",
                            )
                        with col_meta:
                            caption_lines = [clip["title"]]
                            if clip.get("description"):
                                caption_lines.append("")
                                caption_lines.append(clip["description"])
                            if clip.get("hashtags"):
                                caption_lines.append("")
                                caption_lines.append(" ".join(clip["hashtags"]))
                            st.markdown("**Copy-paste caption:**")
                            st.code("\n".join(caption_lines), language=None)
                    else:
                        st.warning("Preview unavailable — use download button below.")
                except Exception:
                    st.warning("Preview unavailable — try downloading from the backend URL.")

        if st.button("⬇️ Download All as ZIP"):
            try:
                zip_resp = api_post(
                    "/download-zip",
                    {
                        "job_id": st.session_state.job_id,
                        "clip_paths": clip_paths,
                    },
                )
                if zip_resp.status_code == 200:
                    st.download_button(
                        label="Save ZIP file",
                        data=zip_resp.content,
                        file_name=f"{st.session_state.job_id}_clips.zip",
                        mime="application/zip",
                        key="zip_download",
                    )
                else:
                    st.error(f"ZIP creation failed: {zip_resp.text}")
            except Exception as exc:
                st.error(f"ZIP download error: {exc}")

    st.markdown("---")
    col_back, col_reset = st.columns(2)
    with col_back:
        if st.button("← Back to Review Clips"):
            st.session_state.processed_clips = []
            st.session_state.step = 3
            st.rerun()
    with col_reset:
        if st.button("🔄 Start Over"):
            reset_app()
