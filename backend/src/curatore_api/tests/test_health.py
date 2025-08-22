from fastapi.testclient import TestClient
from curatore_api.main import app

def test_health():
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert "ok" in r.json()