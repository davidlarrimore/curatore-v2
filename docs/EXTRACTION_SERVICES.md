# Extraction Services Reference

Curatore v2 uses a **triage-based extraction architecture** that analyzes each document before extraction and routes it to the optimal extraction engine.

For detailed pipeline documentation, see [`DOCUMENT_PROCESSING.md`](DOCUMENT_PROCESSING.md).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTRACTION ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│    Document Upload                                               │
│          │                                                       │
│          ▼                                                       │
│    ┌─────────────┐                                              │
│    │   TRIAGE    │  ← Analyzes document, selects engine         │
│    │  (< 100ms)  │                                              │
│    └─────────────┘                                              │
│          │                                                       │
│    ┌─────┼─────┬──────────┐                                     │
│    ▼     ▼     ▼          ▼                                     │
│  ┌────┐ ┌────┐ ┌────┐ ┌────────────┐                           │
│  │fast│ │ext-│ │doc-│ │unsupported │                           │
│  │pdf │ │svc │ │ling│ │  (reject)  │                           │
│  └────┘ └────┘ └────┘ └────────────┘                           │
│    │     │     │                                                 │
│    └─────┴─────┴──────▶ Markdown Output                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Comparison

| Feature | fast_pdf | extraction-service | docling |
|---------|----------|-------------------|---------|
| **Location** | Local (worker) | Container (8010) | External (5001) |
| **Technology** | PyMuPDF | MarkItDown + LibreOffice | IBM Docling Serve |
| **PDF (simple)** | ✅ Fast | ❌ | ✅ |
| **PDF (scanned)** | ❌ | ❌ | ✅ OCR |
| **Office files** | ❌ | ✅ | ✅ |
| **Text/HTML/Email** | ❌ | ✅ | ❌ |
| **Table Extraction** | Basic | Basic | Advanced |
| **Speed** | Very Fast | Fast | Slower |
| **Resource Usage** | Low | Low | High |

## Extraction Engines

### 1. fast_pdf (PyMuPDF)

**Purpose:** Fast local extraction for simple, text-based PDFs.

**Technology:** PyMuPDF (fitz) - runs locally in the Celery worker, no external service call required.

**Supported Extensions:** `.pdf`

**When Used by Triage:**
- PDF has extractable text layer (not scanned)
- Simple layout (< 50 blocks/page)
- Few images (< 3 images/page)
- No complex tables

**Characteristics:**
- Very fast (sub-second for most documents)
- No network latency
- Low resource usage
- Best for reports, articles, simple documents

### 2. extraction-service (MarkItDown)

**Purpose:** Document conversion for Office files, text files, and emails.

**Technology:** MarkItDown + LibreOffice (for legacy format conversion)

**Port:** 8010

**Supported Extensions:**
| Extension | MIME Type | Notes |
|-----------|-----------|-------|
| `.docx` | application/vnd.openxmlformats-officedocument.wordprocessingml.document | Word documents |
| `.doc` | application/msword | Legacy Word (via LibreOffice) |
| `.pptx` | application/vnd.openxmlformats-officedocument.presentationml.presentation | PowerPoint |
| `.ppt` | application/vnd.ms-powerpoint | Legacy PowerPoint (via LibreOffice) |
| `.xlsx` | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | Excel |
| `.xls` | application/vnd.ms-excel | Legacy Excel (via LibreOffice) |
| `.xlsb` | application/vnd.ms-excel.sheet.binary.macroEnabled.12 | Excel Binary (via LibreOffice) |
| `.txt` | text/plain | Plain text |
| `.md` | text/markdown | Markdown |
| `.csv` | text/csv | CSV files |
| `.html`, `.htm` | text/html | HTML files |
| `.xml` | text/xml | XML files |
| `.json` | application/json | JSON files |
| `.msg` | application/vnd.ms-outlook | Outlook emails |
| `.eml` | message/rfc822 | Email files |

**When Used by Triage:**
- All Office documents (< 5MB)
- All text-based files
- All email files
- Unknown file types (fallback)

**API Example:**
```bash
curl -X POST "http://localhost:8010/api/v1/extract" \
  -F "file=@document.docx"
```

**Response:**
```json
{
  "filename": "document.docx",
  "content_markdown": "# Document Content...",
  "content_chars": 1234,
  "method": "markitdown",
  "ocr_used": false,
  "page_count": 5,
  "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
```

### 3. docling (IBM Docling)

**Purpose:** Advanced extraction for complex documents requiring OCR or layout analysis.

**Technology:** IBM Docling with optional OCR engines (EasyOCR, Tesseract)

**Port:** 5001 (external), 5151 (Docker)

**Supported Extensions:**
| Extension | Use Case |
|-----------|----------|
| `.pdf` | Scanned PDFs, complex layouts, tables |
| `.docx`, `.pptx`, `.xlsx` | Large/complex documents (>= 5MB) |
| `.doc`, `.ppt`, `.xls` | Large legacy Office files |

**When Used by Triage:**
- Scanned PDFs (little/no text layer)
- Complex PDF layouts (many blocks, images, tables)
- Large Office files (>= 5MB)
- Documents requiring OCR

**Characteristics:**
- Highest quality extraction
- Advanced table recognition
- OCR for scanned content
- Slower but more accurate

**API Example:**
```bash
curl -X POST "http://localhost:5151/v1/convert/file" \
  -F "files=@document.pdf" \
  -F "to_formats=md" \
  -F "do_ocr=true" \
  -F "pipeline=standard" \
  -F "table_mode=accurate"
```

**Docling Parameters (v1.9.0+):**

| Parameter | Default | Options |
|-----------|---------|---------|
| `to_formats` | `["md"]` | md, json, html, text, doctags |
| `pipeline` | `standard` | standard, simple, vlm |
| `do_ocr` | `true` | true, false |
| `ocr_engine` | `easyocr` | easyocr, rapidocr, tesseract |
| `table_mode` | `accurate` | fast, accurate |
| `image_export_mode` | `embedded` | embedded, placeholder, referenced |

## Unsupported File Types

The following file types are **not supported** for extraction:

| Type | Extensions | Reason |
|------|------------|--------|
| Images | `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`, `.heic` | Standalone image files are not processed. Image OCR is only performed within documents (e.g., scanned PDFs) via the Docling engine. |

## Triage Decision Logic

The triage service (`backend/app/services/triage_service.py`) runs analysis in < 100ms:

### PDF Analysis (using PyMuPDF)

Analyzes first 3 pages for:
| Check | Threshold | Result |
|-------|-----------|--------|
| Text per page | < 100 chars | Needs OCR → `docling` |
| Blocks per page | > 50 | Complex layout → `docling` |
| Images per page | > 3 | Image-heavy → `docling` |
| Tables detected | > 20 drawing lines | Has tables → `docling` |
| None of above | - | Simple text → `fast_pdf` |

### Office File Analysis

Uses file size as a complexity proxy:
| File Size | Engine | Reason |
|-----------|--------|--------|
| < 5 MB | `extraction-service` | Simple document, MarkItDown handles well |
| >= 5 MB | `docling` | Large file likely has complex content |

## Configuration

### config.yml

```yaml
extraction:
  default_engine: extraction-service

  engines:
    # Internal Extraction Service (MarkItDown)
    - name: extraction-service
      display_name: "Internal Extraction Service"
      description: "Built-in extraction using MarkItDown"
      engine_type: extraction-service
      service_url: http://extraction:8010
      timeout: 240
      enabled: true

    # Docling (External)
    - name: docling-external
      display_name: "Docling (Host Machine)"
      description: "Docling running on host machine"
      engine_type: docling
      service_url: http://host.docker.internal:5001
      timeout: 300
      enabled: true
      options:
        to_formats: ["md"]
        ocr_engine: auto
        table_mode: accurate
```

### Docker Compose

```bash
# Enable Docling (optional)
docker-compose --profile docling up -d
```

## Health Checks

```bash
# Extraction Service
curl http://localhost:8010/api/v1/system/health
# {"status":"ok","service":"extraction-service"}

# Docling Service
curl http://localhost:5151/health
# {"status":"ok"}

# Check fast_pdf availability (PyMuPDF in worker)
docker exec curatore-worker python -c "import fitz; print(f'PyMuPDF {fitz.version}')"
```

## Troubleshooting

### PyMuPDF not available

**Error:** `PyMuPDF not available, using fallback routing`

**Cause:** PyMuPDF not installed in worker container

**Solution:**
```bash
docker-compose build --no-cache worker
docker-compose up -d worker
```

### Docling Returns 404

**Error:** `Task result not found`

**Cause:** File format not supported by Docling (e.g., .txt files)

**Solution:** Triage automatically routes unsupported formats to extraction-service

### Images Not Processing

**Error:** `Unsupported file type`

**Cause:** Standalone images are not supported

**Solution:** Image OCR is only available within documents (PDFs). Convert images to PDF first if OCR is needed.

## References

- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling Serve Documentation](https://docling-serve.readthedocs.io/)
- [MarkItDown](https://github.com/microsoft/markitdown)
- [PyMuPDF](https://pymupdf.readthedocs.io/)

## Updated: 2026-02-01

Triage-based architecture with fast_pdf, extraction-service, and docling engines.
