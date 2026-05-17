"""
File management utilities for VideoClipper.
Handles job folder creation, path management, and cleanup.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def create_job_folder(job_id: str) -> str:
    """
    Creates a temporary directory for a job.
    
    Args:
        job_id: Unique identifier for the job (UUID)
        
    Returns:
        Full path to the created job folder as string
        
    Raises:
        Logs error but doesn't crash if folder already exists
    """
    try:
        job_path = Path("temp") / f"job_{job_id}"
        job_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created job folder: {job_path}")
        return str(job_path)
    except Exception as e:
        logger.error(f"Error creating job folder for job_id {job_id}: {str(e)}")
        raise


def get_job_path(job_id: str) -> str:
    """
    Returns the full path to a job's temporary directory.
    
    Does NOT check if the folder exists.
    
    Args:
        job_id: Unique identifier for the job (UUID)
        
    Returns:
        Full path to the job folder as string
    """
    try:
        job_path = Path("temp") / f"job_{job_id}"
        logger.debug(f"Retrieved job path for job_id {job_id}: {job_path}")
        return str(job_path)
    except Exception as e:
        logger.error(f"Error getting job path for job_id {job_id}: {str(e)}")
        raise


def cleanup_job_folder(job_id: str) -> None:
    """
    Deletes the entire temporary directory for a job and all its contents.
    
    Silently ignores if folder doesn't exist.
    
    Args:
        job_id: Unique identifier for the job (UUID)
        
    Returns:
        None
    """
    try:
        job_path = Path("temp") / f"job_{job_id}"
        
        if job_path.exists():
            shutil.rmtree(job_path)
            logger.info(f"Cleaned up job folder: {job_path}")
        else:
            logger.debug(f"Job folder does not exist (no cleanup needed): {job_path}")
            
    except Exception as e:
        logger.error(f"Error cleaning up job folder for job_id {job_id}: {str(e)}")
        raise
