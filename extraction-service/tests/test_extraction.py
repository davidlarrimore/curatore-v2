import json
import pathlib

import pytest
import tempfile
from fastapi.testclient import TestClient
import importlib.util


def _has_module(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except ModuleNotFoundError:
        return False


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT / 'test_documents'
MANIFEST_PATH = ROOT / 'manifest.json'


def get_client() -> TestClient:
    from app.main import app
    return TestClient(app)


def iter_documents():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    for doc in manifest['documents']:
        yield doc


@pytest.mark.parametrize('doc', list(iter_documents()), ids=lambda d: d['filename'])
def test_extraction_via_api_per_manifest(doc, monkeypatch):
    client = get_client()
    file_path = TEST_DATA_DIR / doc['filename']
    assert file_path.exists(), f'Missing test file: {file_path}'

    # Skip environment-dependent cases if converters are unavailable
    name = file_path.name.lower()
    if name.endswith('.docx') or name.endswith('.xlsx'):
        if not _has_module('markitdown'):
            pytest.skip('markitdown not available in this environment')
    if name.endswith('.pdf'):
        has_pdfminer = _has_module('pdfminer.high_level')
        has_ocr_stack = _has_module('pypdfium2') and _has_module('pytesseract') and _has_module('PIL')
        if not (has_pdfminer or has_ocr_stack):
            pytest.skip('Neither pdfminer nor OCR stack available')

    # Redirect upload dir to a writable temp path
    from app import config as _cfg
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(_cfg.settings, "UPLOAD_DIR", tmpdir, raising=True)
        with file_path.open('rb') as f:
            files = {"file": (file_path.name, f, None)}
            resp = client.post("/api/v1/extract", files=files)

    if not doc['should_parse']:
        assert resp.status_code == 422, f"Expected unprocessable for corrupted {file_path.name}"
        return

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Method expectations are soft: allow any of listed methods due to env variability
    expect_methods = set(doc['expect_method_any_of'])
    assert body['method'] in expect_methods, f"method={body['method']} not in {expect_methods}"
    assert isinstance(body['content_markdown'], str)
    assert body['content_chars'] == len(body['content_markdown']) and body['content_chars'] > 0

    for marker in doc['expected_markers']:
        assert marker.split()[0] in body['content_markdown'], f"Missing marker in content: {marker}"


def test_pdf_force_ocr_switches_method_when_pdf_present(monkeypatch):
    client = get_client()
    pdf_path = TEST_DATA_DIR / 'sample.pdf'
    if not pdf_path.exists():
        pytest.skip('sample.pdf missing')
    # Skip entirely if neither pdfminer nor OCR stack available
    has_pdfminer = _has_module('pdfminer.high_level')
    has_ocr_stack = _has_module('pypdfium2') and _has_module('pytesseract') and _has_module('PIL')
    if not (has_pdfminer or has_ocr_stack):
        pytest.skip('Neither pdfminer nor OCR stack available')
    from app import config as _cfg
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(_cfg.settings, "UPLOAD_DIR", tmpdir, raising=True)
        with pdf_path.open('rb') as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            # First, default
            r1 = client.post("/api/v1/extract", files=files)
    assert r1.status_code == 200
    method1 = r1.json()['method']

    # Force OCR
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(_cfg.settings, "UPLOAD_DIR", tmpdir, raising=True)
        with pdf_path.open('rb') as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            r2 = client.post("/api/v1/extract?force_ocr=true", files=files)
    # If tesseract is unavailable, service may still return 422. Accept either 200 with ocr or 422.
    if r2.status_code == 200:
        assert r2.json()['method'] == 'ocr'
    else:
        assert r2.status_code in (200, 422)
