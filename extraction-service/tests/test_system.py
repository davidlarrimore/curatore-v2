from fastapi.testclient import TestClient


def get_client():
    # Import lazily so env monkeypatch (if any) can apply before app loads
    from app.main import app
    return TestClient(app)


def test_health_ok():
    client = get_client()
    r = client.get("/api/v1/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert body.get("service") == "extraction-service"


def test_supported_formats_nonempty():
    client = get_client()
    r = client.get("/api/v1/system/supported-formats")
    assert r.status_code == 200
    body = r.json()
    exts = body.get("extensions") or []
    assert isinstance(exts, list)
    assert len(exts) > 0
    # PDFs are handled by fast_pdf/Docling, not this service
    assert ".docx" in exts

