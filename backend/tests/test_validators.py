"""
Unit and integration tests for VideoClipper backend.
Run with: pytest tests/
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Test validators
from utils.validators import validate_video_file, sanitize_label, validate_clip_bounds


class TestVideoFileValidation:
    """Tests for video file validation."""
    
    def test_valid_video_file(self):
        """Test that valid video files pass validation."""
        is_valid, error_msg = validate_video_file("test.mp4", 100 * 1024 * 1024)
        assert is_valid is True
        assert error_msg == ""
    
    def test_all_supported_formats(self):
        """Test all supported video formats."""
        formats = ["test.mp4", "test.mov", "test.avi", "test.mkv"]
        for filename in formats:
            is_valid, _ = validate_video_file(filename, 50 * 1024 * 1024)
            assert is_valid is True
    
    def test_empty_filename(self):
        """Test that empty filename is rejected."""
        is_valid, error_msg = validate_video_file("", 100 * 1024 * 1024)
        assert is_valid is False
        assert "Filename cannot be empty" in error_msg
    
    def test_empty_file(self):
        """Test that empty file is rejected."""
        is_valid, error_msg = validate_video_file("test.mp4", 0)
        assert is_valid is False
        assert "must be greater than 0" in error_msg
    
    def test_invalid_extension(self):
        """Test that invalid extensions are rejected."""
        is_valid, error_msg = validate_video_file("test.txt", 100 * 1024 * 1024)
        assert is_valid is False
        assert "not allowed" in error_msg
    
    def test_file_too_large(self):
        """Test that files over 500MB are rejected."""
        is_valid, error_msg = validate_video_file("test.mp4", 600 * 1024 * 1024)
        assert is_valid is False
        assert "exceeds limit" in error_msg
    
    def test_max_file_size_boundary(self):
        """Test file at exact 500MB limit."""
        is_valid, _ = validate_video_file("test.mp4", 500 * 1024 * 1024)
        assert is_valid is True


class TestSanitizeLabel:
    """Tests for label sanitization."""
    
    def test_sanitize_spaces_to_underscores(self):
        """Test that spaces are converted to underscores."""
        result = sanitize_label("Hello World")
        assert result == "Hello_World"
    
    def test_remove_special_characters(self):
        """Test that special characters are removed."""
        result = sanitize_label("Hello@World#123!")
        assert "@" not in result and "#" not in result and "!" not in result
        assert "HelloWorld123" in result
    
    def test_truncate_long_labels(self):
        """Test that labels are truncated to 40 chars."""
        long_label = "a" * 50
        result = sanitize_label(long_label)
        assert len(result) == 40
    
    def test_empty_label_fallback(self):
        """Test that empty label returns 'clip' fallback."""
        result = sanitize_label("!!!@@@")
        assert result == "clip"
    
    def test_valid_label_unchanged(self):
        """Test that valid labels are preserved."""
        result = sanitize_label("intro_segment")
        assert result == "intro_segment"


class TestClipBoundsValidation:
    """Tests for clip bounds validation."""
    
    def test_valid_clips(self):
        """Test that valid clips pass validation."""
        clips = [
            {"start": 0.0, "end": 60.0, "label": "Clip 1"},
            {"start": 70.0, "end": 130.0, "label": "Clip 2"},
        ]
        result = validate_clip_bounds(clips)
        assert len(result) == 2
    
    def test_clip_missing_fields(self):
        """Test that clips with missing fields raise error."""
        clips = [{"start": 0.0, "label": "Clip 1"}]  # Missing 'end'
        with pytest.raises(ValueError, match="missing required fields"):
            validate_clip_bounds(clips)
    
    def test_negative_timestamps(self):
        """Test that negative timestamps are rejected."""
        clips = [{"start": -10.0, "end": 50.0, "label": "Clip"}]
        with pytest.raises(ValueError, match="negative timestamps"):
            validate_clip_bounds(clips)
    
    def test_end_before_start(self):
        """Test that end < start is rejected."""
        clips = [{"start": 100.0, "end": 50.0, "label": "Clip"}]
        with pytest.raises(ValueError, match="end must be greater than start"):
            validate_clip_bounds(clips)
    
    def test_clip_too_short(self):
        """Test that clips under 30 seconds are rejected."""
        clips = [{"start": 0.0, "end": 20.0, "label": "Too short"}]
        with pytest.raises(ValueError, match="outside the allowed"):
            validate_clip_bounds(clips)
    
    def test_clip_too_long(self):
        """Test that clips over 180 seconds are rejected."""
        clips = [{"start": 0.0, "end": 200.0, "label": "Too long"}]
        with pytest.raises(ValueError, match="outside the allowed"):
            validate_clip_bounds(clips)
    
    def test_overlapping_clips(self):
        """Test that overlapping clips are detected."""
        clips = [
            {"start": 0.0, "end": 100.0, "label": "Clip 1"},
            {"start": 50.0, "end": 150.0, "label": "Clip 2"},  # Overlaps with first
        ]
        with pytest.raises(ValueError, match="overlap"):
            validate_clip_bounds(clips)
    
    def test_clips_at_boundary(self):
        """Test that clips at exact boundaries are accepted."""
        clips = [
            {"start": 0.0, "end": 100.0, "label": "Clip 1"},
            {"start": 100.0, "end": 150.0, "label": "Clip 2"},  # Touches but doesn't overlap
        ]
        result = validate_clip_bounds(clips)
        assert len(result) == 2


class TestJobStore:
    """Tests for job store operations."""
    
    def test_create_and_get_job(self):
        """Test creating and retrieving a job."""
        from jobs.job_store import create_job, get_job
        
        job_id = "test-job-123"
        create_job(job_id)
        job = get_job(job_id)
        
        assert job is not None
        assert job["status"] == "queued"
        assert job["progress"] == 0
    
    def test_get_nonexistent_job(self):
        """Test that getting nonexistent job returns None."""
        from jobs.job_store import get_job
        
        job = get_job("nonexistent-job")
        assert job is None
    
    def test_update_job(self):
        """Test updating job status."""
        from jobs.job_store import create_job, update_job, get_job
        
        job_id = "update-test-123"
        create_job(job_id)
        update_job(job_id, "processing", "Running...", 50)
        
        job = get_job(job_id)
        assert job["status"] == "processing"
        assert job["progress"] == 50


class TestTranscriptFormatting:
    """Tests for transcript formatting for LLM."""
    
    def test_format_transcript(self):
        """Test transcript formatting."""
        from services.analyzer import format_transcript
        
        segments = [
            {"start": 0.0, "end": 10.5, "text": "Hello world"},
            {"start": 15.0, "end": 30.0, "text": "This is great"},
        ]
        
        result = format_transcript(segments)
        assert "[0:00 → 0:10] Hello world" in result
        assert "[0:15 → 0:30] This is great" in result


class TestLLMResponseParsing:
    """Tests for LLM response parsing."""
    
    def test_parse_valid_json_response(self):
        """Test parsing valid JSON response."""
        from services.analyzer import parse_llm_response
        
        response = json.dumps([
            {"start": 0.0, "end": 60.0, "label": "Intro"},
            {"start": 70.0, "end": 130.0, "label": "Main point"},
        ])
        
        result = parse_llm_response(response)
        assert len(result) == 2
        assert result[0]["label"] == "Intro"
    
    def test_parse_json_with_markdown_fence(self):
        """Test parsing JSON wrapped in markdown code fence."""
        from services.analyzer import parse_llm_response
        
        response = """```json
[
  {"start": 0.0, "end": 60.0, "label": "Clip 1"}
]
```"""
        
        result = parse_llm_response(response)
        assert len(result) == 1
    
    def test_parse_invalid_json(self):
        """Test that invalid JSON raises error."""
        from services.analyzer import parse_llm_response
        
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_llm_response("not valid json")
    
    def test_parse_missing_required_fields(self):
        """Test that missing required fields are caught."""
        from services.analyzer import parse_llm_response
        
        response = json.dumps([
            {"start": 0.0, "label": "Missing end field"}
        ])
        
        with pytest.raises(ValueError, match="missing required"):
            parse_llm_response(response)


class TestAnalyzedClipRepair:
    """Tests for repairing analyzer output before validation."""

    def test_repair_zero_length_clip(self):
        """Test that a zero-length clip is expanded into a valid window."""
        from services.analyzer import _repair_analyzed_clips

        segments = [
            {"start": 0.0, "end": 20.0, "text": "Intro"},
            {"start": 20.0, "end": 45.0, "text": "Main idea"},
            {"start": 45.0, "end": 80.0, "text": "Details"},
        ]
        clips = [{"start": 0.0, "end": 0.0, "label": "Intro"}]

        result = _repair_analyzed_clips(clips, segments)

        assert len(result) == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 30.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
