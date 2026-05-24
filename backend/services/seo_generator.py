import os
import logging
import json
import re
from dotenv import load_dotenv
from .multi_llm import smart_llm_call

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Core SEO Generation Functions ---

def generate_clip_seo(clip: dict, transcript_text: str, channel_niche: str = "general") -> dict:
    """
    Generates a complete YouTube SEO package for a single video clip using an LLM.

    Args:
        clip (dict): The clip dictionary containing 'label', 'start', and 'end'.
        transcript_text (str): The transcript text corresponding to the clip.
        channel_niche (str): The niche of the YouTube channel for context.

    Returns:
        dict: A dictionary with SEO data. Returns a minimal dict on failure.
    """
    # LLM system prompt
    system_prompt = "You are a world-class YouTube SEO expert and content strategist. Your goal is to create viral, keyword-optimized metadata. You must return ONLY a single, valid JSON object and nothing else."

    # Calculate duration
    duration = clip.get('end', 0) - clip.get('start', 0)

    # LLM user prompt
    user_prompt = f"""
    Generate a complete YouTube SEO package for the following video clip.
    The output must be a single, valid JSON object.

    Clip Details:
    - Topic: {clip.get('label', 'Untitled Clip')}
    - Duration: {duration:.0f} seconds
    - Transcript Snippet: "{transcript_text[:600]}..."
    - Channel Niche: {channel_niche}

    Generate the following fields in a JSON object:
    {{
      "title": "A keyword-first, highly clickable title. Maximum 70 characters.",
      "description": "A three-paragraph, engaging description. Start with a strong hook, naturally integrate keywords, and end with a call-to-action. Use paragraphs.",
      "tags": ["list", "of", "15-20", "relevant", "and", "specific", "tags", "including", "long-tail", "keywords"],
      "hashtags": ["#list", "#of", "#5-7", "#relevant", "#hashtags"],
      "category": "A suitable YouTube category (e.g., 'Education', 'Entertainment', 'Howto & Style').",
      "hook": "The powerful first sentence of the description, designed to grab attention in search results and social media previews.",
      "cta": "A compelling call-to-action to include at the end of the description (e.g., 'Subscribe for more insights!', 'Watch the full video here: [link]').",
      "seo_score": "An estimated SEO score from 0 to 100 based on the quality and optimization of the generated content. Be realistic."
    }}
    """

    try:
        # Call the LLM with automatic fallback
        response = smart_llm_call(prompt=user_prompt, system=system_prompt, temperature=0.5, max_tokens=1500)
        
        # Clean and parse the JSON response
        json_text = response['text'].strip()
        # Find the JSON object within the response text
        match = re.search(r'\{.*\}', json_text, re.DOTALL)
        if not match:
            raise json.JSONDecodeError("No JSON object found in LLM response.", json_text, 0)
        
        json_data = json.loads(match.group(0))

        # Validate essential keys
        required_keys = ['title', 'description', 'tags', 'hashtags', 'seo_score']
        if not all(key in json_data for key in required_keys):
            raise KeyError("LLM response is missing one or more required keys.")
            
        logging.info(f"Successfully generated SEO for clip: {clip.get('label')}")
        return json_data

    except (RuntimeError, json.JSONDecodeError, KeyError) as e:
        logging.error(f"Failed to generate or parse SEO for clip '{clip.get('label')}': {e}")
        # Return a default, empty SEO structure on failure
        return {
            'title': clip.get('label', 'Untitled Clip'),
            'description': transcript_text[:500], # Use transcript as fallback
            'tags': [],
            'hashtags': [],
            'seo_score': 0,
            'hook': '',
            'cta': '',
            'category': 'Education'
        }

def generate_full_video_seo(segments: list, clips: list, video_title: str = "") -> dict:
    """
    Generates SEO for the complete video by summarizing all clips.

    Args:
        segments (list): The full transcript segments.
        clips (list): The list of generated clips.
        video_title (str): An optional title for the full video.

    Returns:
        dict: A dictionary with 'title', 'description', 'all_tags', and 'posting_recommendation'.
    """
    if not clips:
        return {}

    # Combine clip topics and create chapter markers
    full_description_parts = []
    all_tags = set()
    
    # Start with a general intro
    intro = f"In this video, we dive into several key topics related to {video_title or clips[0].get('label', '')}."
    full_description_parts.append(intro)
    full_description_parts.append("\n⏱ CHAPTERS:")

    for clip in clips:
        minutes, seconds = divmod(int(clip['start']), 60)
        timestamp = f"{minutes:02d}:{seconds:02d}"
        full_description_parts.append(f"{timestamp} - {clip.get('label', 'Clip')}")
        if 'tags' in clip and isinstance(clip['tags'], list):
            all_tags.update(clip['tags'])

    # Combine all parts into a single description
    final_description = "\n".join(full_description_parts)

    # Generate a posting recommendation
    recommendation = "Post this video during peak audience hours (check your YouTube Analytics). Use the generated thumbnail and SEO to maximize reach."

    return {
        "title": video_title or f"Highlights from the video: {clips[0].get('label')}",
        "description": final_description,
        "all_tags": list(all_tags),
        "posting_recommendation": recommendation
    }

def generate_seo_for_all_clips(clips: list[dict], segments: list[dict], channel_niche: str = "general") -> list[dict]:
    """
    Iterates through clips and generates SEO for each one.

    Args:
        clips (list[dict]): The list of clips to process.
        segments (list[dict]): The full transcript segments.
        channel_niche (str): The YouTube channel's niche.

    Returns:
        list[dict]: The updated list of clips with merged SEO data.
    """
    updated_clips = []
    total_clips = len(clips)
    for i, clip in enumerate(clips):
        logging.info(f"Generating SEO for clip {i+1}/{total_clips}: \"{clip.get('label')}\"")
        
        # Extract transcript text that overlaps with the clip's timeframe
        clip_start, clip_end = clip['start'], clip['end']
        clip_transcript = " ".join(
            seg['text'] for seg in segments if seg['start'] < clip_end and seg['end'] > clip_start
        ).strip()

        if not clip_transcript:
            logging.warning(f"No transcript found for clip {i+1}, using label as fallback.")
            clip_transcript = clip.get('label', '')

        # Generate SEO for the individual clip
        seo_data = generate_clip_seo(clip, clip_transcript, channel_niche)
        
        # Merge the SEO data into the clip dictionary
        clip.update(seo_data)
        updated_clips.append(clip)

    logging.info("Finished generating SEO for all clips.")
    return updated_clips

def format_youtube_description(clip: dict, chapters: list = None) -> str:
    """
    Formats a complete, copy-paste ready YouTube description.

    Args:
        clip (dict): The clip dictionary containing SEO fields.
        chapters (list, optional): A list of chapter dicts {'time': '00:00', 'label': '...'}

    Returns:
        str: A formatted string for the YouTube description box.
    """
    hook = clip.get('hook', '')
    description_body = clip.get('description', '')
    hashtags = " ".join(clip.get('hashtags', []))
    
    # Build description parts
    parts = [hook, "\n", description_body]

    # Add timestamps if provided
    if chapters:
        parts.append("\n\n⏱ TIMESTAMPS:")
        for chap in chapters:
            parts.append(f"{chap['time']} - {chap['label']}")

    # Add hashtags
    if hashtags:
        parts.append("\n\n" + hashtags)

    # Add branding footer
    parts.append("\n\n━━━━━━━━━━━━━━━━━━━━")
    parts.append("✦ Created with VideoClipper by Gulfam")
    parts.append("━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(parts)

# --- Module Initialization ---
if __name__ == "__main__":
    logging.info("seo_generator.py loaded OK")
    print("seo_generator.py loaded OK")
