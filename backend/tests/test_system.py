import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "llm_connected" in data


def test_supported_formats(client):
    response = client.get("/api/config/supported-formats")
    assert response.status_code == 200
    data = response.json()
    assert ".pdf" in data["supported_extensions"]


def test_list_items(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    data = response.json()
    assert any(item["name"] == "Document Processing" for item in data)
