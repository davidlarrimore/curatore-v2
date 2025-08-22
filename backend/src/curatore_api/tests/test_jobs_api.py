from fastapi.testclient import TestClient
from curatore_api.main import app

def test_jobs_list_empty():
    c = TestClient(app)
    r = c.get("/jobs")
    assert r.status_code == 200
    assert isinstance(r.json().get("jobs"), list)