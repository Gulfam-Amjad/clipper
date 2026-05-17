"""
In-memory job store for VideoClipper.
Thread-safe dictionary-based storage for job metadata and progress.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global job storage dictionary
jobs = {}

# Lock for thread-safe access
_jobs_lock = threading.Lock()


def create_job(job_id: str) -> None:
    """
    Creates a new job entry in the store.
    
    Initializes with default queued state.
    
    Args:
        job_id: Unique identifier for the job
        
    Returns:
        None
    """
    try:
        with _jobs_lock:
            jobs[job_id] = {
                "status": "queued",
                "progress": 0,
                "current_step": "Job queued...",
                "clips": None,
                "error": None,
            }
            logger.info(f"Created new job: {job_id}")
    except Exception as e:
        logger.error(f"Error creating job {job_id}: {str(e)}")
        raise


def update_job(job_id: str, status: str, current_step: str, progress: int) -> None:
    """
    Updates a job's status, current step, and progress.
    
    Args:
        job_id: Unique identifier for the job
        status: Current processing status
        current_step: Human-readable description of current step
        progress: Progress percentage (0-100)
        
    Returns:
        None
    """
    try:
        with _jobs_lock:
            if job_id not in jobs:
                logger.warning(f"Job not found for update: {job_id}")
                return
            
            jobs[job_id]["status"] = status
            jobs[job_id]["current_step"] = current_step
            jobs[job_id]["progress"] = progress
            
            logger.debug(f"Updated job {job_id}: status={status}, progress={progress}%")
    except Exception as e:
        logger.error(f"Error updating job {job_id}: {str(e)}")
        raise


def get_job(job_id: str) -> Optional[dict]:
    """
    Retrieves a job from the store.
    
    Args:
        job_id: Unique identifier for the job
        
    Returns:
        Job dictionary if found, None otherwise
    """
    try:
        with _jobs_lock:
            if job_id not in jobs:
                logger.debug(f"Job not found: {job_id}")
                return None
            
            job = jobs[job_id].copy()
            logger.debug(f"Retrieved job: {job_id}")
            return job
    except Exception as e:
        logger.error(f"Error retrieving job {job_id}: {str(e)}")
        raise


def mark_done(job_id: str, clips: list) -> None:
    """
    Marks a job as completed with final clips.
    
    Args:
        job_id: Unique identifier for the job
        clips: List of clip dictionaries
        
    Returns:
        None
    """
    try:
        with _jobs_lock:
            if job_id not in jobs:
                logger.warning(f"Job not found for completion: {job_id}")
                return
            
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["current_step"] = "All clips ready!"
            jobs[job_id]["clips"] = clips
            
            logger.info(f"Marked job as done: {job_id} with {len(clips)} clip(s)")
    except Exception as e:
        logger.error(f"Error marking job as done {job_id}: {str(e)}")
        raise


def mark_error(job_id: str, error_msg: str) -> None:
    """
    Marks a job as failed with an error message.
    
    Args:
        job_id: Unique identifier for the job
        error_msg: Human-readable error message
        
    Returns:
        None
    """
    try:
        with _jobs_lock:
            if job_id not in jobs:
                logger.warning(f"Job not found for error marking: {job_id}")
                return
            
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = error_msg
            jobs[job_id]["current_step"] = "Processing failed."
            jobs[job_id]["progress"] = 0
            
            logger.error(f"Marked job as error: {job_id} - {error_msg}")
    except Exception as e:
        logger.error(f"Error marking job as error {job_id}: {str(e)}")
        raise
