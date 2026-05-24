import os
import json
import hashlib
import logging
import pathlib
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Cache Configuration ---
CACHE_DIR = pathlib.Path("temp/transcript_cache")

# --- Core Caching Functions ---
def get_file_hash(file_path: str) -> str:
    """
    Generates an MD5 hash for the content of a file.

    Args:
        file_path (str): The path to the file.

    Returns:
        str: The hex digest of the MD5 hash, or an empty string if an error occurs.
    """
    try:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except FileNotFoundError:
        logging.warning(f"Hash calculation failed: File not found at {file_path}")
        return ""
    except Exception as e:
        logging.error(f"An unexpected error occurred during hash calculation for {file_path}: {e}")
        return ""

def get_cached_transcript(file_path: str) -> list[dict] | None:
    """
    Retrieves a cached transcript if it exists for the given file.

    Args:
        file_path (str): The path to the original media file.

    Returns:
        list[dict] | None: The list of transcript segments if found, otherwise None.
    """
    # Ensure cache directory exists before attempting to read
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    file_hash = get_file_hash(file_path)
    if not file_hash:
        return None

    cache_file = CACHE_DIR / f"{file_hash}.json"

    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"Cache HIT for file: {os.path.basename(file_path)} (hash: {file_hash})")
            return data.get("segments") # Return segments specifically
        except (json.JSONDecodeError, KeyError) as e:
            logging.error(f"Failed to read or parse cache file {cache_file}: {e}")
            return None
    else:
        logging.info(f"Cache MISS for file: {os.path.basename(file_path)} (hash: {file_hash})")
        return None

def save_transcript_cache(file_path: str, segments: list[dict]) -> None:
    """
    Saves a transcript to the cache. This function never raises an exception.

    Args:
        file_path (str): The path to the original media file.
        segments (list[dict]): The transcript segments to cache.
    """
    try:
        # Create the cache directory if it doesn't exist
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        file_hash = get_file_hash(file_path)
        if not file_hash:
            logging.warning("Could not save transcript to cache because file hash failed.")
            return

        cache_file = CACHE_DIR / f"{file_hash}.json"
        
        # Cache includes metadata for future use
        cache_data = {
            "original_file": os.path.basename(file_path),
            "cached_at": datetime.utcnow().isoformat(),
            "segments": segments
        }

        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        
        logging.info(f"Transcript cached successfully for {os.path.basename(file_path)} at {cache_file}")

    except Exception as e:
        # Caching failures are logged but should not interrupt the main workflow
        logging.error(f"Failed to save transcript cache for {file_path}: {e}")

# --- Cache Maintenance Functions ---
def clear_old_cache(max_age_hours: int = 24) -> int:
    """
    Deletes cache files older than a specified number of hours.

    Args:
        max_age_hours (int): The maximum age of a cache file in hours.

    Returns:
        int: The number of deleted cache files.
    """
    if not CACHE_DIR.exists():
        return 0

    deleted_count = 0
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

    try:
        for cache_file in CACHE_DIR.glob("*.json"):
            try:
                file_mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                if file_mod_time < cutoff_time:
                    cache_file.unlink()
                    deleted_count += 1
                    logging.info(f"Deleted old cache file: {cache_file.name}")
            except Exception as e:
                logging.error(f"Could not process or delete cache file {cache_file.name}: {e}")
        
        if deleted_count > 0:
            logging.info(f"Cleared {deleted_count} old cache files.")
        else:
            logging.info("No old cache files to clear.")
            
    except Exception as e:
        logging.error(f"An error occurred during cache cleanup: {e}")

    return deleted_count

def get_cache_stats() -> dict:
    """
    Calculates statistics about the current state of the transcript cache.

    Returns:
        dict: A dictionary containing the number of cached items and their total size.
    """
    stats = {"cached_transcripts": 0, "total_size_mb": 0.0}
    if not CACHE_DIR.exists():
        return stats

    try:
        cached_files = list(CACHE_DIR.glob("*.json"))
        total_size_bytes = sum(f.stat().st_size for f in cached_files)
        
        stats["cached_transcripts"] = len(cached_files)
        stats["total_size_mb"] = round(total_size_bytes / (1024 * 1024), 2)
    except Exception as e:
        logging.error(f"Could not calculate cache stats: {e}")

    return stats

# --- Module Initialization ---
if __name__ == "__main__":
    logging.info("transcript_cache.py loaded OK")
    # Example usage:
    # Create a dummy file for testing
    # with open("temp/dummy_video.mp4", "wb") as f:
    #     f.write(os.urandom(1024))
    # save_transcript_cache("temp/dummy_video.mp4", [{"start": 0, "end": 1, "text": "Hello"}])
    # print(get_cached_transcript("temp/dummy_video.mp4"))
    # print(get_cache_stats())
    # clear_old_cache(0) # Clear immediately
    # print(get_cache_stats())
    print("transcript_cache.py loaded OK")
