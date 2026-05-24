import os
import logging
import json
import pathlib
import pickle
from dotenv import load_dotenv

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- YouTube API Constants ---
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = pathlib.Path("temp/youtube_token.pkl")
CLIENT_SECRETS_PATH = pathlib.Path(os.getenv("YOUTUBE_CLIENT_SECRETS", "youtube_client_secrets.json"))

# --- Authentication Functions ---

def get_youtube_credentials() -> Credentials | None:
    """
    Loads or refreshes user credentials for the YouTube API.

    Returns:
        Credentials | None: A valid Credentials object or None if authentication is needed.
    """
    creds = None
    try:
        # Load token from file if it exists
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, "rb") as token:
                creds = pickle.load(token)
        
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logging.info("YouTube credentials expired. Refreshing token...")
                creds.refresh(Request())
                # Save the refreshed credentials
                TOKEN_FILE.parent.mkdir(exist_ok=True)
                with open(TOKEN_FILE, "wb") as token:
                    pickle.dump(creds, token)
                logging.info("YouTube token refreshed and saved.")
            else:
                # No valid credentials, authentication is required
                return None
        return creds
    except Exception as e:
        logging.error(f"An error occurred with YouTube credentials: {e}")
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink() # Corrupted token file
            logging.warning("Removed potentially corrupted YouTube token file.")
        return None

def is_youtube_connected() -> bool:
    """
    Checks if the application has valid, non-expired YouTube credentials.

    Returns:
        bool: True if connected, False otherwise.
    """
    try:
        return get_youtube_credentials() is not None
    except Exception as e:
        logging.error(f"YouTube connection check failed: {e}")
        return False

def get_auth_url() -> str:
    """
    Starts the OAuth 2.0 flow and returns the authorization URL for the user.

    Returns:
        str: The URL the user must visit to authorize the application.

    Raises:
        RuntimeError: If the client secrets file is not found.
    """
    if not CLIENT_SECRETS_PATH.is_file():
        raise RuntimeError(
            "YouTube client secrets file not found. "
            "Download 'client_secrets.json' from the Google Cloud Console.\n"
            "Go to: console.cloud.google.com → APIs & Services → Credentials\n"
            "→ Create Credentials → OAuth 2.0 Client ID (for Desktop app)\n"
            "→ Download JSON, rename it to 'youtube_client_secrets.json', and place it in the 'backend/' folder."
        )
    
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_PATH), SCOPES)
        # The redirect_uri must match one of the authorized redirect URIs for the client
        auth_url, _ = flow.authorization_url(prompt='consent')
        # Store flow in a temporary file to be retrieved by complete_auth
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        with open(TOKEN_FILE.parent / 'youtube_flow.pkl', 'wb') as f:
            pickle.dump(flow, f)
        return auth_url
    except Exception as e:
        logging.error(f"Failed to create YouTube auth URL: {e}")
        raise RuntimeError(f"Could not initiate YouTube authentication flow: {e}")

def complete_auth(auth_code: str) -> bool:
    """
    Completes the OAuth 2.0 flow using the authorization code from the user.

    Args:
        auth_code (str): The authorization code provided by Google after user consent.

    Returns:
        bool: True on successful authentication and token save, False otherwise.
    """
    try:
        flow_file = TOKEN_FILE.parent / 'youtube_flow.pkl'
        if not flow_file.exists():
            raise RuntimeError("Authentication flow not initiated. Please call get_auth_url first.")
        
        with open(flow_file, 'rb') as f:
            flow = pickle.load(f)
            
        flow.fetch_token(code=auth_code)
        creds = flow.credentials

        # Save the credentials for the next run
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
        
        # Clean up the temporary flow file
        flow_file.unlink()
        
        logging.info("YouTube authentication successful. Token saved.")
        return True
    except Exception as e:
        logging.error(f"Failed to complete YouTube authentication: {e}")
        return False

# --- Video Upload Functions ---

def upload_clip_to_youtube(video_path: str, title: str, description: str, tags: list, category_id: str = "22", privacy: str = "private") -> dict:
    """
    Uploads a single video file to YouTube.

    Args:
        video_path (str): Path to the video file.
        title (str): The video title.
        description (str): The video description.
        tags (list): A list of tags for the video.
        category_id (str): YouTube category ID. Defaults to "22" (People & Blogs).
        privacy (str): Video privacy status ('public', 'private', 'unlisted').

    Returns:
        dict: A dictionary with upload details on success.

    Raises:
        RuntimeError: If authentication fails or the upload fails.
    """
    creds = get_youtube_credentials()
    if not creds:
        raise RuntimeError("YouTube authentication required. Please connect your account.")

    try:
        youtube = build("youtube", "v3", credentials=creds)
        
        body = {
            "snippet": {
                "title": title[:100],  # YouTube title limit is 100 chars
                "description": description,
                "tags": tags,
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy
            }
        }

        # Callback for upload progress
        def on_upload_progress(status):
            progress = int(status.progress() * 100)
            if progress % 20 == 0 and progress > 0:
                 logging.info(f"YouTube upload progress: {progress}%")

        media = MediaFileUpload(video_path, chunksize=1024*1024, resumable=True)
        
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = request.execute()
        
        video_id = response['id']
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        logging.info(f"Successfully uploaded video '{title}' to YouTube. URL: {youtube_url}")

        return {
            "youtube_id": video_id,
            "youtube_url": youtube_url,
            "title": title,
            "privacy": privacy
        }

    except HttpError as e:
        error_content = json.loads(e.content.decode('utf-8'))
        error_message = error_content.get('error', {}).get('message', 'Unknown YouTube API error')
        logging.error(f"YouTube API HttpError: {error_message}")
        raise RuntimeError(f"Failed to upload to YouTube: {error_message}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during YouTube upload: {e}")
        raise RuntimeError(f"An unexpected error occurred during YouTube upload: {e}")


def upload_all_clips(clips: list[dict], job_folder: str, privacy: str = "private") -> list[dict]:
    """
    Uploads all processed clips to YouTube sequentially.

    Args:
        clips (list[dict]): List of clip dictionaries.
        job_folder (str): The folder where the final clip files are stored.
        privacy (str): The privacy status for all uploaded clips.

    Returns:
        list[dict]: The updated clips list with upload results.
    """
    if not is_youtube_connected():
        logging.error("Cannot upload clips. YouTube account is not connected.")
        for clip in clips:
            clip['youtube_error'] = "Account not connected"
        return clips

    updated_clips = []
    total_clips = len(clips)
    for i, clip in enumerate(clips):
        logging.info(f"Uploading clip {i+1} of {total_clips}: '{clip.get('title', 'Untitled')}'")
        
        video_file_path = clip.get("output_path")
        if not video_file_path or not os.path.exists(video_file_path):
            logging.error(f"Skipping upload for clip {i+1}, file not found at {video_file_path}")
            clip['youtube_error'] = "Video file not found"
            updated_clips.append(clip)
            continue

        try:
            upload_result = upload_clip_to_youtube(
                video_path=video_file_path,
                title=clip.get("title", "AI Generated Clip"),
                description=clip.get("description", ""),
                tags=clip.get("tags", []),
                privacy=privacy
            )
            clip.update(upload_result)
        except RuntimeError as e:
            logging.error(f"Failed to upload clip {i+1}: {e}")
            clip['youtube_error'] = str(e)
        
        updated_clips.append(clip)

    logging.info("Finished uploading all clips to YouTube.")
    return updated_clips

# --- Module Initialization ---
if __name__ == "__main__":
    logging.info("youtube_uploader.py loaded OK")
    print("youtube_uploader.py loaded OK")
    # print(f"Is YouTube Connected: {is_youtube_connected()}")
    # if not is_youtube_connected():
    #     print(f"Auth URL: {get_auth_url()}")
    #     code = input("Enter auth code: ")
    #     complete_auth(code)
