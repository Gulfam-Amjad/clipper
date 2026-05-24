from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import subprocess
import logging
import os
import pathlib
import textwrap
import numpy as np
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Core Thumbnail Generation Functions ---

def extract_best_frame(video_path: str, clip_start: float, clip_end: float, output_path: str) -> str | None:
    """
    Samples frames from a video clip and saves the one with the highest visual detail.

    Args:
        video_path (str): Path to the source video.
        clip_start (float): Start time of the clip in seconds.
        clip_end (float): End time of the clip in seconds.
        output_path (str): Path to save the final best frame.

    Returns:
        str | None: The path to the saved frame, or None on failure.
    """
    temp_dir = pathlib.Path(output_path).parent / "temp_frames"
    try:
        temp_dir.mkdir(exist_ok=True)
        
        # Sample 5 frames from the middle 60% of the clip
        clip_duration = clip_end - clip_start
        sample_start = clip_start + clip_duration * 0.2
        sample_duration = clip_duration * 0.6
        
        frames = []
        for i in range(5):
            timestamp = sample_start + (sample_duration * i / 4)
            temp_frame_path = temp_dir / f"frame_{i}.jpg"
            
            # FFmpeg command to extract a single frame
            command = [
                'ffmpeg', '-y',
                '-ss', str(timestamp),
                '-i', video_path,
                '-vframes', '1',
                '-q:v', '2', # High quality
                str(temp_frame_path)
            ]
            
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Calculate variance
            with Image.open(temp_frame_path) as img:
                grayscale_img = img.convert("L")
                variance = np.array(grayscale_img).std() ** 2
                frames.append({'path': temp_frame_path, 'variance': variance})
        
        # Find the frame with the highest variance
        if not frames:
            raise RuntimeError("No frames were extracted from the video.")
            
        best_frame = max(frames, key=lambda x: x['variance'])
        logging.info(f"Best frame selected with variance {best_frame['variance']:.2f}")
        
        # Copy the best frame to the final output path
        shutil.copy(best_frame['path'], output_path)
        
        return output_path

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.error(f"FFmpeg failed to extract frames: {e}")
        return None
    except Exception as e:
        logging.error(f"Error extracting best frame: {e}")
        return None
    finally:
        # Clean up temporary frames
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def create_thumbnail(frame_path: str, clip_label: str, clip_duration: float, output_path: str, style: str = "youtube") -> str:
    """
    Creates a professional YouTube-style thumbnail from a frame and text.

    Args:
        frame_path (str): Path to the best video frame.
        clip_label (str): The main title for the thumbnail.
        clip_duration (float): Duration of the clip in seconds for the badge.
        output_path (str): Path to save the final thumbnail JPEG.
        style (str): The style preset ('youtube', 'tiktok', 'instagram').

    Returns:
        str: The path to the saved thumbnail.
    """
    try:
        # --- 1. Canvas and Background Frame ---
        base_img = Image.open(frame_path).convert("RGBA")
        
        # Resize/crop to 1280x720 (cover)
        target_aspect = 1280 / 720
        img_aspect = base_img.width / base_img.height
        
        if img_aspect > target_aspect: # Wider than target
            new_height = 720
            new_width = int(new_height * img_aspect)
            resized = base_img.resize((new_width, new_height), Image.LANCZOS)
            left = (new_width - 1280) / 2
            cropped = resized.crop((left, 0, left + 1280, 720))
        else: # Taller than target
            new_width = 1280
            new_height = int(new_width / img_aspect)
            resized = base_img.resize((new_width, new_height), Image.LANCZOS)
            top = (new_height - 720) / 2
            cropped = resized.crop((0, top, 1280, top + 720))

        canvas = Image.new("RGBA", (1280, 720))
        canvas.paste(cropped, (0, 0))
        draw = ImageDraw.Draw(canvas)

        # --- 2. Darken Bottom Gradient ---
        gradient = Image.new('L', (1, 720))
        for y in range(720):
            opacity = int(255 * (max(0, y - 720 * 0.6) / (720 * 0.4)) * 0.65)
            gradient.putpixel((0, y), opacity)
        gradient = gradient.resize(canvas.size)
        black_overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        black_overlay.putalpha(gradient)
        canvas = Image.alpha_composite(canvas, black_overlay)
        draw = ImageDraw.Draw(canvas)

        # --- 3. Left Accent Bar ---
        style_colors = {"youtube": "#FF0000", "tiktok": "#00F2EA", "instagram": "#E1306C", "default": "#1f77b4"}
        accent_color = style_colors.get(style, style_colors["default"])
        draw.rectangle([0, 0, 8, 720], fill=accent_color)

        # --- 4. Main Title Text ---
        try:
            font_main = ImageFont.truetype("arialbd.ttf", 52)
        except IOError:
            logging.warning("Arial Bold not found, using default font.")
            font_main = ImageFont.load_default()
        
        wrapped_text = textwrap.fill(clip_label, width=28)
        x, y = 30, 720 - 180
        shadow_offset = 3
        draw.text((x + shadow_offset, y + shadow_offset), wrapped_text, font=font_main, fill=(0, 0, 0, 180))
        draw.text((x, y), wrapped_text, font=font_main, fill=(255, 255, 255))

        # --- 5. Duration Badge ---
        try:
            font_badge = ImageFont.truetype("arialbd.ttf", 28)
        except IOError:
            font_badge = ImageFont.load_default()
        
        minutes, seconds = divmod(int(clip_duration), 60)
        duration_text = f"{minutes}:{seconds:02d}"
        
        bbox = draw.textbbox((0, 0), duration_text, font=font_badge)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        
        padding = 12
        badge_w, badge_h = text_w + padding * 2, text_h + padding * 2
        badge_x, badge_y = 1280 - 15 - badge_w, 15
        
        draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=8, fill=(0, 0, 0, int(255 * 0.8)))
        draw.text((badge_x + padding, badge_y + padding - 5), duration_text, font=font_badge, fill=(255, 255, 255))

        # --- 6. Watermark ---
        try:
            font_watermark = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font_watermark = ImageFont.load_default()
        watermark_text = "✦ Gulfam"
        wm_bbox = draw.textbbox((0,0), watermark_text, font=font_watermark)
        wm_w = wm_bbox[2] - wm_bbox[0]
        draw.text((1280 - 15 - wm_w, 720 - 15 - (wm_bbox[3]-wm_bbox[1])), watermark_text, font=font_watermark, fill=(255, 255, 255, int(255 * 0.7)))

        # --- 7. Vignette ---
        vignette = Image.new('L', (1280, 720))
        draw_vignette = ImageDraw.Draw(vignette)
        for i in range(300):
            alpha = int(255 * (1 - (i / 300)**0.5))
            draw_vignette.ellipse([i, i, 1280 - i, 720 - i], fill=alpha)
        vignette = vignette.filter(ImageFilter.GaussianBlur(100))
        dark_vignette = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        dark_vignette.putalpha(vignette)
        canvas = Image.alpha_composite(canvas, dark_vignette)

        # --- 8. Save Final Image ---
        final_image = canvas.convert("RGB")
        final_image.save(output_path, "JPEG", quality=95)
        logging.info(f"Thumbnail created successfully at {output_path}")
        return output_path

    except Exception as e:
        logging.error(f"Failed to create thumbnail: {e}")
        # As a fallback, just copy the frame
        if pathlib.Path(frame_path).exists():
            shutil.copy(frame_path, output_path)
            return output_path
        return ""


def generate_clip_thumbnail(video_path: str, clip: dict, output_folder: str, index: int) -> str | None:
    """
    Orchestrates the thumbnail generation for a single clip.

    Args:
        video_path (str): Path to the source video.
        clip (dict): The clip dictionary, containing 'start', 'end', 'label'.
        output_folder (str): The folder to save the thumbnail in.
        index (int): The index of the clip.

    Returns:
        str | None: The path to the generated thumbnail, or None on failure.
    """
    try:
        output_folder_path = pathlib.Path(output_folder)
        output_folder_path.mkdir(parents=True, exist_ok=True)
        
        frame_output_path = output_folder_path / f"best_frame_{index}.jpg"
        thumb_output_path = output_folder_path / f"pro_thumb_{index}.jpg"

        # Step 1: Extract the best frame
        best_frame_path = extract_best_frame(video_path, clip['start'], clip['end'], frame_output_path)
        
        if not best_frame_path:
            logging.warning(f"Could not extract frame for clip {index}, thumbnail generation skipped.")
            return None

        # Step 2: Create the thumbnail
        duration = clip['end'] - clip['start']
        final_thumb_path = create_thumbnail(best_frame_path, clip['label'], duration, thumb_output_path)

        if final_thumb_path:
            clip["pro_thumbnail_path"] = final_thumb_path
            return final_thumb_path
        return None
        
    except Exception as e:
        logging.error(f"Failed to generate thumbnail for clip {index}: {e}")
        return None


def generate_all_thumbnails(video_path: str, clips: list[dict], output_folder: str) -> list[dict]:
    """
    Generates thumbnails for all provided clips sequentially.

    Args:
        video_path (str): Path to the source video.
        clips (list[dict]): A list of clip dictionaries.
        output_folder (str): The base folder for all output.

    Returns:
        list[dict]: The updated list of clips with thumbnail paths.
    """
    updated_clips = []
    for i, clip in enumerate(clips):
        logging.info(f"Generating thumbnail for clip {i+1}/{len(clips)}...")
        generate_clip_thumbnail(video_path, clip, output_folder, i + 1)
        updated_clips.append(clip) # Append clip regardless of thumbnail success
    
    logging.info("Finished generating all thumbnails.")
    return updated_clips

# --- Module Initialization ---
if __name__ == "__main__":
    logging.info("thumbnail_generator.py loaded OK")
    print("thumbnail_generator.py loaded OK")
