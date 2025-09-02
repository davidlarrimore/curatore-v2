import os
import shutil
import tempfile
from pathlib import Path


# Configure a writable files root for tests before importing app modules.
# Use the system temp directory to avoid cluttering the repo tree.
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="curatore_pytest_"))

# Point storage to the session temp directory
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


def pytest_sessionstart(session):
    """Best-effort cleanup of any past leftover test dirs in repo root."""
    try:
        repo_backend_dir = Path(__file__).resolve().parents[1]
        # Remove legacy test dirs created by older conftest runs
        for p in repo_backend_dir.glob("test_files_*"):
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass
