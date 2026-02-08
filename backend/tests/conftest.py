import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# Configure a writable temp directory for tests before importing app modules.
# Use the system temp directory to avoid cluttering the repo tree.
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="curatore_pytest_"))

# Object storage is now required - tests should use MinIO or mock it
os.environ.setdefault("USE_OBJECT_STORAGE", "true")

# Keep external integrations quiet during tests
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("EXTRACTION_SERVICE_URL", "")


@pytest.fixture
def client():
    """FastAPI test client fixture.

    Provides a TestClient instance for testing API endpoints.
    Import is done inside the fixture to avoid import errors during test collection.
    """
    from app.main import app
    return TestClient(app)


@pytest.fixture
def mock_current_user():
    """Mock authenticated user fixture."""
    mock_user = MagicMock()
    mock_user.id = "test-user-id"
    mock_user.email = "test@example.com"
    mock_user.organization_id = "test-org-id"
    mock_user.role = "admin"
    return mock_user


@pytest.fixture
def auth_headers():
    """Mock authentication headers."""
    return {"Authorization": "Bearer test-token"}


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "asyncio: mark test as async")


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
