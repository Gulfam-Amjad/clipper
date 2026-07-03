import logging
import os

from dotenv import load_dotenv


load_dotenv()


logger = logging.getLogger(__name__)


class Config:
	GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
	GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

	TEMP_DIR = os.getenv("TEMP_DIR", "temp")
	MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "500"))
	WATERMARK_TEXT = os.getenv("WATERMARK_TEXT", "✦ Gulfam")
	DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")

	REDIS_URL = os.getenv("REDIS_URL", "")

	CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "30"))
	MAX_JOB_AGE_HOURS = int(os.getenv("MAX_JOB_AGE_HOURS", "1"))

	MUSIC_DIR = os.getenv("MUSIC_DIR", "music")
	DEFAULT_MUSIC_STYLE = os.getenv("DEFAULT_MUSIC_STYLE", "lofi")

	BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

	ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
	ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")


config = Config()

if config.GROQ_API_KEY == "":
	logger.warning(
		"GROQ_API_KEY is empty. The app will start, but Groq-powered features may fail until a key is configured."
	)

if config.GEMINI_API_KEY == "":
	logger.info(
		"GEMINI_API_KEY is empty. Gemini fallback is disabled; only Groq providers will be used."
	)
