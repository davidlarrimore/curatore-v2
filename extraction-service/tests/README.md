Test data and framework

- Fixtures in `extraction-service/tests/fixtures_docs.py` generate sample files at test time:
  - `sample.txt`, `sample.md` with inline markers.
  - `sample.docx`, `sample.xlsx` built as minimal OOXML zips containing markers.
  - `sample.pdf` built with a tiny PDF writer containing a text marker.
  - Corrupt variants are created by truncating bytes: `sample_corrupt.*`.

- A session-scoped autouse fixture in `extraction-service/tests/conftest.py` materializes files under
  `extraction-service/test_documents` and writes `extraction-service/manifest.json`.

- `test_extraction.py` walks the manifest and posts each file to `/api/v1/extract`:
  - For valid files, it asserts method is one of expected methods and markers appear in `content_markdown`.
  - For corrupt files, it expects `422 Unprocessable Entity`.
  - A separate test verifies forcing OCR for PDFs changes the method to `ocr` when possible.

- `test_pdf_quality.py` unit-tests the PDF text-layer quality heuristic used to trigger OCR.

Notes

- OCR requires `tesseract` binary; if unavailable, the force-OCR test allows a `422` outcome.
- LibreOffice-based conversions are not required for these tests; methods are asserted flexibly where environment-dependent.

