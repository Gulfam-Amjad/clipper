"""
Pydantic v2 models for VideoClipper API responses and data structures.
"""

from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class ProcessResponse(BaseModel):
    """Response returned when a video processing job is created."""
    job_id: str
    message: str


class ClipInfo(BaseModel):
    """Information about a single video clip."""
    filename: str
    label: str
    start: float
    end: float
    duration: float
    
    @field_validator("duration", mode="after")
    @classmethod
    def validate_duration(cls, v: float, info) -> float:
        """
        Validates that duration equals (end - start).
        This is a calculated field that should be automatically set.
        """
        data = info.data
        start = data.get("start", 0)
        end = data.get("end", 0)
        expected_duration = end - start
        if abs(v - expected_duration) > 0.001:  # Allow small floating-point differences
            raise ValueError(f"Duration must equal (end - start). Got {v}, expected {expected_duration}")
        return v


class JobStatus(BaseModel):
    """Status and progress information for a video processing job."""
    status: Literal["queued", "downloading", "extracting_audio", "transcribing", "analyzing", "cutting", "creating_shorts", "done", "error"]
    current_step: str
    progress: int
    clips: Optional[list[ClipInfo]] = None
    shorts_clips: Optional[list[ClipInfo]] = None
    music_style: Optional[str] = "lofi"
    error: Optional[str] = None
    
    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v):
        """Ensures progress is between 0 and 100."""
        if not 0 <= v <= 100:
            raise ValueError("Progress must be between 0 and 100")
        return v
