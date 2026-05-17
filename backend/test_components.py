#!/usr/bin/env python
"""Quick test script to verify backend components work."""

print("Testing backend components...")

# Test validators
print("\n1. Testing validators...")
from utils.validators import validate_video_file, sanitize_label, validate_clip_bounds
result = validate_video_file("test.mp4", 100 * 1024 * 1024)
assert result[0] is True, "Valid video should pass"
print("✓ validate_video_file works")

label = sanitize_label("Hello World!")
assert label == "Hello_World", "Label sanitization failed"
print("✓ sanitize_label works")

clips = [
    {"start": 0.0, "end": 60.0, "label": "Clip 1"},
    {"start": 70.0, "end": 130.0, "label": "Clip 2"},
]
result = validate_clip_bounds(clips)
assert len(result) == 2, "Clip validation failed"
print("✓ validate_clip_bounds works")

# Test schemas
print("\n2. Testing Pydantic schemas...")
from models.schemas import ClipInfo, ProcessResponse, JobStatus
clip = ClipInfo(filename="test.mp4", label="Test", start=0.0, end=60.0, duration=60.0)
assert clip.label == "Test", "ClipInfo creation failed"
print("✓ ClipInfo model works")

resp = ProcessResponse(job_id="123", message="Started")
assert resp.job_id == "123", "ProcessResponse failed"
print("✓ ProcessResponse model works")

# Test job store
print("\n3. Testing job store...")
from jobs.job_store import create_job, get_job, update_job, mark_done, mark_error
create_job("test-job-1")
job = get_job("test-job-1")
assert job["status"] == "queued", "Job creation failed"
print("✓ create_job works")

update_job("test-job-1", "processing", "Running", 50)
job = get_job("test-job-1")
assert job["progress"] == 50, "Job update failed"
print("✓ update_job works")

mark_done("test-job-1", [])
job = get_job("test-job-1")
assert job["status"] == "done", "Mark done failed"
print("✓ mark_done works")

create_job("test-job-2")
mark_error("test-job-2", "Test error")
job = get_job("test-job-2")
assert job["status"] == "error", "Mark error failed"
print("✓ mark_error works")

# Test file manager
print("\n4. Testing file manager...")
from utils.file_manager import create_job_folder, get_job_path
try:
    path = create_job_folder("test-folder-123")
    assert "test-folder-123" in path, "Folder creation failed"
    print("✓ create_job_folder works")
    
    path2 = get_job_path("test-folder-456")
    assert "test-folder-456" in path2, "Get job path failed"
    print("✓ get_job_path works")
finally:
    # Cleanup
    import shutil
    from pathlib import Path
    for folder in ["test-folder-123", "test-folder-456"]:
        p = Path("temp") / f"job_{folder}"
        if p.exists():
            shutil.rmtree(p)

print("\n✅ All backend components working correctly!")
