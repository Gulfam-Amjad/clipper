# VideoClipper AI

A production-style AI clipping studio that turns long videos or YouTube links into ranked, captioned, platform-ready short clips.

## What It Does

1. **Import** a local video (MP4, MOV, MKV, AVI) or paste a YouTube URL
2. **Transcribe** audio using Groq Whisper with word-level timestamps; long videos are automatically chunked
3. **Select clips** with Groq Llama 3.3 70B, with optional Gemini Flash fallback when `GEMINI_API_KEY` is configured
4. **Review** ranked ideas with titles, descriptions, hashtags, timestamps, virality score, hook score, and content score
5. **Export** fast cuts or polished vertical 9:16 edits with blurred fill, animated captions, audio normalization, visual cleanup, and background music
6. **Download** individual MP4s or all clips as a ZIP

## Prerequisites

- **Python 3.10+**
- **ffmpeg** and **ffprobe** installed and available on your PATH  
  Verify with: `ffmpeg -version` and `ffprobe -version`
- A **Groq API key** — get one free at [console.groq.com](https://console.groq.com)
- Optional **Gemini API key** for fallback clip selection — get one at [aistudio.google.com](https://aistudio.google.com)
- **Node.js 18+** for the React frontend

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
GEMINI_API_KEY=optional_gemini_key_here
```

Replace `your_actual_groq_api_key_here` with your real Groq API key. `GEMINI_API_KEY` is optional, but useful as a free fallback if Groq is unavailable or rate-limited.

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

## Running the App

You need **two terminals** — one for the backend, one for the frontend.

**Terminal 1 — Backend (FastAPI):**

```bash
uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — Frontend (React + Vite):**

```bash
cd frontend
npm run dev
```

Then open the Vite URL shown in the terminal, usually `http://localhost:5173`.

## How to Use

### Step 1 — Import Source
- Choose a local video, or paste a YouTube URL
- Click **Upload and Analyze** or **Import YouTube Link**

### Step 2 — Transcribe and Analyze
- The app uploads/downloads the source, transcribes it, then asks the AI to find complete, viral-worthy moments
- Adjust the clip count and length range before generating ideas

### Step 3 — Review Clips
- Review titles, scores, descriptions, hashtags, and timestamps
- Check/uncheck clips to include and adjust start/end times if needed

### Step 4 — Export
- Toggle optional features:
  - **Vertical 9:16** — converts to 1080×1920 with a blurred-background fill (looks great on Shorts / TikTok / Reels)
  - **Animated captions** — burns word-by-word highlighted captions, correctly synced to each clip
  - **Normalize audio** — evens out loudness to a platform-friendly level
  - **Visual cleanup** — masks a corner logo/name area
  - **Background Music** — upload audio and mix it softly under the original voice
- Use **Create Fast Cuts** for quick review or **Render Polished Edits** for final clips
- Preview clips in the browser, copy captions, download individually, or download all as ZIP

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
│   ├── src/                 # React + TypeScript frontend
│   ├── package.json
│   └── app.py               # Legacy Streamlit UI fallback
├── uploads/                 # Temporary uploaded videos
├── outputs/                 # Processed clips and ZIPs
├── music/                   # Uploaded background music
├── .env                     # API keys (not committed)
├── requirements.txt
└── README.md
```

## API Endpoints

| Method | Endpoint             | Description                    |
|--------|----------------------|--------------------------------|
| GET    | `/health`            | Health check                   |
| POST   | `/upload`            | Upload video or music file     |
| POST   | `/youtube-info`      | Fetch YouTube video metadata   |
| POST   | `/download-youtube`  | Download a YouTube source      |
| POST   | `/transcribe`        | Transcribe uploaded video      |
| POST   | `/select-clips`      | AI clip selection              |
| POST   | `/process-clips`     | Cut and process clips          |
| POST   | `/download-zip`      | Download all clips as ZIP      |
| GET    | `/download/{name}`   | Download a single output file  |
| GET    | `/preview-upload/{name}` | Preview the imported source |

## Notes

- Files in `uploads/` and `outputs/` older than 60 minutes are automatically cleaned up
- All ffmpeg operations use subprocess with full error reporting
- YouTube imports use `yt-dlp`; only download videos you own or have permission to reuse
- The React frontend can be pointed at another backend with `VITE_API_URL`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Problem | Solution |
|---------|----------|
| `Cannot connect to backend` | Make sure uvicorn is running on port 8000 |
| Frontend cannot call API | Confirm the React app is on port 5173 or set CORS origins in `backend/main.py` |
| `No AI provider is configured` | Add `GROQ_API_KEY` or `GEMINI_API_KEY` to `.env` and restart backend |
| YouTube download fails | Update `yt-dlp` with `pip install -U yt-dlp` and confirm ffmpeg is installed |
| `ffprobe failed` | Ensure ffmpeg is installed and on PATH |
| Transcription slow | Large videos take longer; Groq API speed varies |

## License

MIT
