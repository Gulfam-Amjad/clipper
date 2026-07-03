# VideoClipper AI

An AI-powered video clipping tool that turns long videos into shareable highlight clips.

## What It Does

1. **Upload** a video (MP4, MOV, MKV, AVI)
2. **Transcribe** the audio using Groq Whisper with word-level timestamps (long videos are automatically chunked)
3. **Select clips** — Groq Llama 3.3 70B analyzes the transcript and picks the most viral-worthy moments, each with a catchy title, a ready-to-post description, hashtags, and a virality score (1–10). You control how many clips and their length range.
4. **Export** — ffmpeg cuts each clip, with optional vertical 9:16 conversion (blurred-background fill, no black bars), animated word-by-word captions synced to each clip, audio loudness normalization, and background music
5. **Download** individual clips (with copy-paste captions) or everything as a ZIP

## Prerequisites

- **Python 3.10+**
- **ffmpeg** and **ffprobe** installed and available on your PATH  
  Verify with: `ffmpeg -version` and `ffprobe -version`
- A **Groq API key** — get one free at [console.groq.com](https://console.groq.com)

## Setup

### 1. Clone and enter the project

```bash
cd clipper
```

### 2. Create a virtual environment (if not already done)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Configure environment variables

Create or edit `.env` in the project root:

```
GROQ_API_KEY=your_actual_groq_api_key_here
```

Replace `your_actual_groq_api_key_here` with your real Groq API key.

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

## Running the App

You need **two terminals** — one for the backend, one for the frontend.

**Terminal 1 — Backend (FastAPI):**

```bash
uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — Frontend (Streamlit):**

```bash
streamlit run frontend/app.py
```

Then open the Streamlit URL shown in the terminal (usually `http://localhost:8501`).

## How to Use

### Step 1 — Upload
- Click **Upload a video** and choose an MP4, MOV, MKV, or AVI file
- Click **Upload Video**, then **Proceed to Transcription**

### Step 2 — Transcribe
- Click **🎙️ Transcribe Video**
- Wait for Groq Whisper to finish (typically under a minute for short videos)
- Review the transcript in the expander, then click **Proceed to Clip Selection**

### Step 3 — Review Clips
- AI suggests 3–5 highlight clips with titles, timestamps, and reasons
- Check/uncheck clips to include, adjust start/end times if needed
- Click **Proceed to Export**

### Step 4 — Export
- Toggle optional features:
  - **Vertical 9:16** — converts to 1080×1920 with a blurred-background fill (looks great on Shorts / TikTok / Reels)
  - **Animated captions** — burns word-by-word highlighted captions, correctly synced to each clip
  - **Normalize audio** — evens out loudness to a platform-friendly level
  - **Background Music** — upload an MP3 and mix at 20% volume
- Click **🚀 Process & Export Clips**
- Preview clips in the browser, copy the generated caption (title + description + hashtags), download individually, or download all as ZIP
- Click **🔄 Start Over** to process a new video

## Project Structure

```
clipper/
├── backend/
│   ├── main.py              # FastAPI server and API endpoints
│   ├── transcriber.py       # Audio extraction + Groq Whisper
│   ├── clip_selector.py     # Groq Llama clip selection
│   ├── video_processor.py   # ffmpeg clip cutting, shorts, music, ZIP
│   ├── subtitle_generator.py
│   └── utils.py
├── frontend/
│   └── app.py               # Streamlit UI
├── uploads/                 # Temporary uploaded videos
├── outputs/                 # Processed clips and ZIPs
├── music/                   # Uploaded background music
├── .env                     # API keys (not committed)
├── requirements.txt
└── README.md
```

## API Endpoints

| Method | Endpoint           | Description                    |
|--------|--------------------|--------------------------------|
| GET    | `/health`          | Health check                   |
| POST   | `/upload`          | Upload video or music file     |
| POST   | `/transcribe`      | Transcribe uploaded video      |
| POST   | `/select-clips`    | AI clip selection              |
| POST   | `/process-clips`   | Cut and process clips          |
| POST   | `/download-zip`    | Download all clips as ZIP      |
| GET    | `/download/{name}` | Download a single output file  |

## Notes

- Files in `uploads/` and `outputs/` older than 60 minutes are automatically cleaned up
- All ffmpeg operations use subprocess with full error reporting
- The app does **not** support YouTube URL downloading — upload local video files only

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Cannot connect to backend` | Make sure uvicorn is running on port 8000 |
| `GROQ_API_KEY is not set` | Add your key to `.env` and restart the backend |
| `ffprobe failed` | Ensure ffmpeg is installed and on PATH |
| Transcription slow | Large videos take longer; Groq API speed varies |

## License

MIT
