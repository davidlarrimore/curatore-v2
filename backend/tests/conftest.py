import os
import shutil
import tempfile
from pathlib import Path


# Configure a writable files root for tests before importing app modules.
_SESSION_DIR = Path(
    tempfile.mkdtemp(prefix="test_files_", dir=str(Path(__file__).resolve().parents[1]))
)

# Point storage to a temp directory inside the repo (writable on macOS/Linux)
os.environ.setdefault("FILES_ROOT", str(_SESSION_DIR))
os.environ.setdefault("UPLOAD_DIR", "uploaded_files")
os.environ.setdefault("PROCESSED_DIR", "processed_files")
os.environ.setdefault("BATCH_DIR", "batch_files")

# Keep external integrations quiet during tests
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("EXTRACTION_SERVICE_URL", "")

# Ensure subdirs exist proactively (mirrors DocumentService.ensure_directories)
for sub in ("uploaded_files", "processed_files", "batch_files"):
    Path(_SESSION_DIR / sub).mkdir(parents=True, exist_ok=True)


def pytest_sessionfinish(session, exitstatus):
    """Cleanup temporary test files after the test session."""
    try:
        shutil.rmtree(_SESSION_DIR, ignore_errors=True)
    except Exception:
        pass

