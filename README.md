# VideoClipper 🎬

An AI-powered video analysis tool that automatically identifies and extracts the most important clips from your videos. Using advanced transcription and language models, VideoClipper turns lengthy videos into bite-sized, shareable clips.

## Features

- 🤖 **AI-Powered Analysis**: Uses Groq's Llama 3.3 LLM to intelligently identify key moments
- 🎯 **Guided & Auto Modes**: Let AI decide what's important, or provide guidance on what to look for
- ⚡ **Fast Processing**: Leverages Groq's fast inference for quick results
- 🎥 **Multiple Format Support**: Works with MP4, MOV, AVI, and MKV videos (max 500MB)
- 📊 **Real-time Progress**: Track processing status with live updates
- 🔄 **4-5 Optimized Clips**: Generates 30-180 second clips for maximum shareability

## Architecture

### Backend (FastAPI)
- **Audio Extraction**: Extracts mono 16kHz MP3 audio from video files
- **Transcription**: Uses Groq Whisper API for accurate speech-to-text
- **Clip Analysis**: LLM analyzes transcript to identify key moments
- **Video Cutting**: FFmpeg creates clean, re-encoded video clips
- **Job Management**: In-memory job store with thread-safe operations

### Frontend (Streamlit)
- User-friendly interface for video upload and processing
- Real-time progress tracking
- Clip preview and download functionality
- Support for both guided and auto modes

## Prerequisites

### System Requirements
- Python 3.11+
- FFmpeg (for video/audio processing)
- 2GB+ RAM for video processing
- Groq API key (free tier available at https://console.groq.com)

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd clipper
```

2. **Set up environment variables**
Create a `.env` file in the root directory:
```
GROQ_API_KEY=your_api_key_here
BACKEND_URL=http://localhost:8000  # For frontend development
```

3. **Install FFmpeg**

   **Windows (with Chocolatey):**
   ```bash
   choco install ffmpeg
   ```
   
   **macOS (with Homebrew):**
   ```bash
   brew install ffmpeg
   ```
   
   **Linux (Ubuntu/Debian):**
   ```bash
   sudo apt-get install ffmpeg
   ```

## Running Locally

### Backend

```bash
cd backend
pip install -r requirements.txt
python main.py
```

The API will be available at `http://localhost:8000`
- Interactive docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Frontend

In a separate terminal:
```bash
cd frontend
pip install -r requirements.txt
streamlit run app.py
```

The app will open at `http://localhost:8501`

## Docker Deployment

### Build and run with Docker

```bash
# Build the backend image
docker build -t videoclipper-backend ./backend

# Run the container
docker run -p 8000:8000 \
  -e GROQ_API_KEY=your_api_key_here \
  -v $(pwd)/temp:/app/temp \
  videoclipper-backend
```

## API Endpoints

### POST /process
Upload a video and start processing.

**Request:**
```bash
curl -X POST "http://localhost:8000/process" \
  -F "video=@video.mp4" \
  -F "guidance=find interesting moments"
```

**Response:**
```json
{
  "job_id": "uuid-string",
  "message": "Processing started"
}
```

### GET /status/{job_id}
Get current processing status.

**Response:**
```json
{
  "status": "analyzing",
  "current_step": "Analyzing content (Step 3 of 4)...",
  "progress": 60,
  "clips": null,
  "error": null
}
```

### GET /download/{job_id}/{filename}
Download a generated clip.

### DELETE /cleanup/{job_id}
Delete temporary files for a job.

### GET /health
Health check endpoint.

## Processing Pipeline

```
Upload Video
    ↓
[1] Extract Audio (16kHz mono MP3)
    ↓
[2] Transcribe (Groq Whisper API)
    ↓
[3] Analyze Transcript (Groq Llama 3.3)
    ↓
[4] Cut Video Clips (FFmpeg re-encoding)
    ↓
Download Clips
```

## Configuration

### Video Limits
- **Max File Size**: 500MB
- **Supported Formats**: MP4, MOV, AVI, MKV
- **Clip Duration**: 30-180 seconds
- **Clips Generated**: 4-5 clips per video

### Processing Performance
- **Audio Extraction**: ~30 seconds (varies by video length)
- **Transcription**: ~1-2 minutes (Groq API)
- **Analysis**: ~30 seconds (LLM processing)
- **Clip Cutting**: ~2-5 minutes (depends on clip count and video codec)

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| GROQ_API_KEY | Yes | - | Groq API key for LLM and Whisper API |
| BACKEND_URL | No | http://localhost:8000 | Backend API URL for frontend |
| LOG_LEVEL | No | INFO | Python logging level |

## Troubleshooting

### "ffmpeg not found"
Ensure FFmpeg is installed and in your system PATH.

### "GROQ_API_KEY not set"
Add your Groq API key to the `.env` file.

### Video upload fails with "File too large"
Maximum file size is 500MB. Try compressing or splitting your video.

### Transcription returns empty segments
The audio quality may be poor. Try a video with clearer speech.

### Clips are too short or too long
The LLM constraints enforce 30-180 second clips. The system may not find enough suitable clips in the transcript.

## Development

### Running Tests

```bash
cd backend
pytest tests/
```

### Code Quality

```bash
# Format code
black backend/ frontend/

# Lint
pylint backend/
```

## Performance Tips

1. **Use clear, well-spoken content** for better transcription accuracy
2. **Shorter videos process faster** - videos under 10 minutes are ideal
3. **Use guided mode** when you know what you're looking for
4. **Auto mode works best** for educational/interview content

## Limitations

- Requires internet connection for Groq API calls
- Depends on transcription accuracy for good results
- Background noise may affect clip quality
- Non-English content may have reduced accuracy
- Processing time scales with video length

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- Check the troubleshooting section
- Review API documentation at `/docs`
- Check logs in backend console output

## Future Enhancements

- [ ] Multi-language support
- [ ] Custom clip duration preferences
- [ ] Batch processing
- [ ] Clip previews
- [ ] Custom output formats
- [ ] AWS/Cloud deployment templates
- [ ] Advanced filtering by topic/sentiment
- [ ] Subtitle extraction and editing
