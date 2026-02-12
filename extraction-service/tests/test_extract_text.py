import io
import tempfile

from fastapi.testclient import TestClient


def test_extract_plain_text_uses_text_method_and_no_ocr(monkeypatch):
    # Redirect uploads to a temporary directory to avoid writing under /app
    with tempfile.TemporaryDirectory() as tmpdir:
        # Late import so we can patch settings after modules are loaded
        from app import config
        monkeypatch.setattr(config.settings, "UPLOAD_DIR", tmpdir, raising=True)

        from app.main import app
        client = TestClient(app)

        content = b"Hello from extraction-service tests!\n"
        files = {
            "file": ("sample.txt", io.BytesIO(content), "text/plain"),
        }

        r = client.post("/api/v1/extract", files=files)
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["filename"] == "sample.txt"
        assert body["method"] in ("text", "markitdown", "markitdown+ocr") or body["method"] == "text"
        # For .txt inputs path in service returns method "text"
        assert body["method"] == "text"
        assert body["ocr_used"] is False
        assert body["content_chars"] > 0
        assert "Hello" in body["content_markdown"]

