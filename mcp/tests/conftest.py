# Test Configuration
"""Pytest fixtures for MCP Gateway tests."""

from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.main import app
from fastapi.testclient import TestClient

# Ensure auth is enforced during tests (non-empty = auth required)
_TEST_SERVICE_API_KEY = "test-service-key"
settings.service_api_key = _TEST_SERVICE_API_KEY


@pytest.fixture
def client():
    """Test client with auth header."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {_TEST_SERVICE_API_KEY}"}


@pytest.fixture
def sample_contract():
    """Sample tool contract from backend."""
    return {
        "name": "search_assets",
        "description": "Search organization assets",
        "category": "search",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
        "output_schema": {
            "type": "array",
            "description": "Search results",
        },
        "side_effects": False,
        "is_primitive": True,
        "payload_profile": "thin",
        "exposure_profile": {"procedure": True, "agent": True},
        "requires_llm": False,
        "requires_session": True,
        "tags": ["search", "assets"],
    }


@pytest.fixture
def sample_contracts(sample_contract):
    """List of sample contracts."""
    return [
        sample_contract,
        {
            "name": "get_content",
            "description": "Get document content",
            "category": "search",
            "version": "1.0.0",
            "input_schema": {
                "type": "object",
                "properties": {
                    "asset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Asset IDs",
                    },
                },
                "required": ["asset_ids"],
            },
            "output_schema": {"type": "object"},
            "side_effects": False,
            "is_primitive": True,
            "payload_profile": "full",
            "exposure_profile": {"procedure": True, "agent": True},
            "requires_llm": False,
            "requires_session": True,
            "tags": ["search", "content"],
        },
        {
            "name": "send_email",
            "description": "Send email notification",
            "category": "notify",
            "version": "1.0.0",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {"type": "object"},
            "side_effects": True,  # Has side effects - should be blocked
            "is_primitive": True,
            "payload_profile": "full",
            "exposure_profile": {"procedure": True, "agent": False},
            "requires_llm": False,
            "requires_session": True,
            "tags": ["notify", "email"],
        },
    ]


@pytest.fixture
def mock_backend_client():
    """Mock backend client."""
    with patch("app.handlers.tools_list.backend_client") as mock:
        mock.get_contracts = AsyncMock(return_value=[])
        mock.get_contract = AsyncMock(return_value=None)
        mock.execute_function = AsyncMock(return_value={"status": "ok", "data": []})
        yield mock


@pytest.fixture
def sample_execution_result():
    """Sample function execution result."""
    return {
        "status": "ok",
        "message": "Search completed",
        "data": [
            {"id": "asset-1", "title": "Document 1", "score": 0.95},
            {"id": "asset-2", "title": "Document 2", "score": 0.87},
        ],
        "metadata": {"query": "test"},
        "items_processed": 2,
        "items_failed": 0,
        "duration_ms": 150,
    }
