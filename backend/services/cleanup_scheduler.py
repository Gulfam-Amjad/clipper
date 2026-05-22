"""Background cleanup scheduler for VideoClipper temp job folders."""

import logging
import os
import pathlib
import shutil
from datetime import datetime, timedelta

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:
    class BackgroundScheduler:  # type: ignore[override]
        """Fallback scheduler used when APScheduler is unavailable."""

        def __init__(self) -> None:
            self.running = False

        def add_job(self, *args: object, **kwargs: object) -> None:
            return None

        def start(self) -> None:
            self.running = True

        def shutdown(self, wait: bool = False) -> None:
            self.running = False


# Configure module-level logging.
logger = logging.getLogger(__name__)


def cleanup_old_jobs(temp_dir: str = "temp", max_age_hours: int = 1) -> int:
    """Delete temp job folders older than the configured age threshold."""
    try:
        # Validate the temporary directory before scanning for jobs.
        temp_path = pathlib.Path(temp_dir)
        if not temp_path.exists():
            logger.warning("Temp directory does not exist: %s", temp_dir)
            return 0

        # Compute the cutoff time once so each folder can be compared consistently.
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        # Scan only job folders that match the expected naming pattern.
        deleted_count = 0
        for folder in temp_path.glob("job_*"):
            try:
                # Skip anything that is not a directory.
                if not folder.is_dir():
                    continue

                # Check the folder modification time against the cutoff.
                folder_mtime = datetime.fromtimestamp(os.path.getmtime(folder))
                if folder_mtime >= cutoff_time:
                    continue

                # Remove folders that are older than the retention period.
                shutil.rmtree(folder)
                deleted_count += 1
                logger.info("Auto-cleaned job folder: %s", folder.name)
            except Exception as exc:
                logger.warning("Failed to clean job folder %s: %s", folder, exc)
                continue

        # Log the final summary for observability.
        logger.info("Cleanup complete: %s folders removed", deleted_count)
        return deleted_count
    except Exception as exc:
        logger.exception("Unexpected error during cleanup: %s", exc)
        return 0


def start_cleanup_scheduler() -> BackgroundScheduler:
    """Start the background scheduler that periodically cleans old job folders."""
    try:
        # Create a fresh scheduler instance for the app process.
        scheduler = BackgroundScheduler()

        # Run once immediately so startup does not wait for the first interval.
        scheduler.add_job(
            cleanup_old_jobs,
            trigger="date",
            run_date=datetime.now(),
            id="cleanup_old_jobs_initial",
            replace_existing=True,
        )

        # Run the cleanup every 30 minutes to keep temp storage under control.
        scheduler.add_job(
            cleanup_old_jobs,
            trigger="interval",
            minutes=30,
            id="cleanup_old_jobs_interval",
            replace_existing=True,
        )

        # Start the scheduler after all jobs are registered.
        scheduler.start()
        logger.info("Cleanup scheduler started — runs every 30 minutes")
        return scheduler
    except Exception:
        logger.exception("Failed to start cleanup scheduler")
        raise


def stop_cleanup_scheduler(scheduler: BackgroundScheduler) -> None:
    """Safely stop the background cleanup scheduler."""
    try:
        # Only attempt shutdown when the scheduler is actively running.
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Cleanup scheduler stopped")
    except Exception:
        logger.exception("Failed to stop cleanup scheduler")


# Allow direct execution for a simple sanity check.
if __name__ == "__main__":
    scheduler = start_cleanup_scheduler()
    print("Scheduler running — press Ctrl+C to stop")
    import time

    time.sleep(5)
    stop_cleanup_scheduler(scheduler)