import os
import pathlib
import importlib.util
import sys
import pytest

# Import fixtures_docs by file path to avoid package-relative imports issues
_HERE = pathlib.Path(__file__).resolve().parent
_FD_PATH = _HERE / "fixtures_docs.py"
_spec = importlib.util.spec_from_file_location("fixtures_docs", str(_FD_PATH))
assert _spec and _spec.loader
fixtures_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures_docs)  # type: ignore
create_all_docs = fixtures_docs.create_all_docs
write_manifest = fixtures_docs.write_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_DOC_DIR = ROOT / "test_documents"
MANIFEST_PATH = ROOT / "manifest.json"


@pytest.fixture(scope="session", autouse=True)
def _materialize_test_documents():
    # Create all sample documents and write manifest once per test session
    TEST_DOC_DIR.mkdir(parents=True, exist_ok=True)
    create_all_docs(TEST_DOC_DIR)
    write_manifest(MANIFEST_PATH, TEST_DOC_DIR)
    yield
