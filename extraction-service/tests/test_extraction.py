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
        keyword = marker.split()[0]
        # MarkItDown may escape underscores in markdown output
        assert keyword in body['content_markdown'] or keyword.replace("_", r"\_") in body['content_markdown'], \
            f"Missing marker in content: {marker}"


