# Document Processing Pipeline

This document describes how Curatore processes documents from upload through search indexing using the intelligent **triage-based extraction system**.

## Overview

Curatore uses an intelligent **triage → route** architecture that analyzes each document before extraction to select the optimal extraction engine. This approach:
- **Maximizes speed** for simple documents (local extraction, no service calls)
- **Maximizes quality** for complex documents (advanced OCR and layout analysis)
- **Eliminates redundant processing** (no separate enhancement phase)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DOCUMENT PROCESSING PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  ┌──────────┐    ┌───────────────┐    ┌─────────────────┐    ┌──────────────────────┐  │
│  │  UPLOAD  │───▶│    TRIAGE     │───▶│   EXTRACTION    │───▶│      INDEXING        │  │
│  │          │    │  (< 100ms)    │    │ (engine-routed) │    │     (pgvector)       │  │
│  └──────────┘    └───────────────┘    └─────────────────┘    └──────────────────────┘  │
│       │                 │                     │                        │               │
│       │                 │                     │                        │               │
│       ▼                 ▼                     ▼                        ▼               │
│   Asset created    Analyze doc,         Markdown in              Searchable           │
│   status=pending   select engine        MinIO bucket             in pgvector          │
│                                         triage_engine set        indexed_at set       │
│                                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Triage System

The triage phase performs lightweight document analysis (typically < 100ms) to determine the optimal extraction engine.

### Triage Decision Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   TRIAGE DECISION                                        │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│                              Document arrives for extraction                             │
│                                          │                                               │
│                                          ▼                                               │
│                              ┌─────────────────────┐                                    │
│                              │  Detect file type   │                                    │
│                              └─────────────────────┘                                    │
│                                          │                                               │
│            ┌─────────────────┬───────────┼───────────┬─────────────────┐                │
│            ▼                 ▼           ▼           ▼                 ▼                │
│       ┌─────────┐      ┌─────────┐  ┌─────────┐  ┌─────────┐    ┌─────────┐            │
│       │   PDF   │      │  Office │  │  Image  │  │  Text   │    │ Unknown │            │
│       └─────────┘      └─────────┘  └─────────┘  └─────────┘    └─────────┘            │
│            │                │            │            │              │                  │
│            ▼                ▼            ▼            ▼              ▼                  │
│    ┌───────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   ┌──────────┐          │
│    │ Analyze with  │  │ Check    │  │UNSUPPORTED│ │extraction│   │extraction│          │
│    │  PyMuPDF:     │  │ file     │  │(standalone│ │-service  │   │-service  │          │
│    │ - text layer? │  │ size     │  │ images    │ │(MarkIt   │   │(fallback)│          │
│    │ - complexity? │  └──────────┘  │ not       │ │Down)     │   └──────────┘          │
│    └───────────────┘       │        │ supported)│ └──────────┘                          │
│         │    │             │        └──────────┘                                        │
│   Simple │    │ Complex    │                                                            │
│   text   │    │ or scanned │ < 5MB      >= 5MB                                          │
│         ▼    ▼            ▼            ▼                                                │
│    ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐                                 │
│    │fast_pdf │  │ docling │  │extraction│  │ docling │                                 │
│    │(PyMuPDF)│  │(OCR/    │  │-service  │  │(layout) │                                 │
│    └─────────┘  │layout)  │  │(MarkIt   │  └─────────┘                                 │
│                 └─────────┘  │Down)     │                                               │
│                              └──────────┘                                               │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### PDF Triage Analysis

For PDFs, PyMuPDF analyzes the first 3 pages to determine:

| Check | Threshold | Result |
|-------|-----------|--------|
| Text per page | < 100 chars | Needs OCR → `docling` |
| Blocks per page | > 50 | Complex layout → `docling` |
| Images per page | > 3 | Image-heavy → `docling` |
| Tables detected | > 20 drawing lines | Has tables → `docling` |
| None of above | - | Simple text → `fast_pdf` |

### Office File Triage

For Office documents, file size is used as a complexity proxy:

| File Size | Engine | Reason |
|-----------|--------|--------|
| < 5 MB | `extraction-service` | Simple document, MarkItDown handles well |
| >= 5 MB | `docling` | Large file likely has complex content |

## Extraction Engines

Curatore uses four extraction engines, each optimized for specific document types:

### 1. fast_pdf (PyMuPDF)

**Purpose**: Fast local extraction for simple, text-based PDFs

**Technology**: PyMuPDF (fitz) - direct text extraction without external service calls

**Supported Extensions**:
| Extension | MIME Type |
|-----------|-----------|
| `.pdf` | application/pdf |

**When Used**:
- PDF has extractable text layer (not scanned)
- Simple layout (< 50 blocks/page)
- Few images (< 3 images/page)
- No complex tables

**Characteristics**:
- Very fast (local processing)
- No network latency
- Good for reports, articles, simple documents

### 2. extraction-service (MarkItDown)

**Purpose**: Document conversion for Office files, text files, and emails

**Technology**: MarkItDown + LibreOffice (for legacy format conversion)

**Supported Extensions**:
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
| `.msg` | application/vnd.ms-outlook | Outlook emails |
| `.eml` | message/rfc822 | Email files |

**When Used**:
- All Office documents (simple, < 5MB)
- All text-based files
- All email files
- Unknown file types (fallback)

**Characteristics**:
- Good balance of speed and quality
- Handles most common document types
- LibreOffice converts legacy formats

### 3. docling (IBM Docling)

**Purpose**: Advanced extraction for complex documents requiring OCR or layout analysis

**Technology**: IBM Docling with optional Tesseract OCR

**Supported Extensions**:
| Extension | MIME Type | Use Case |
|-----------|-----------|----------|
| `.pdf` | application/pdf | Scanned PDFs, complex layouts |
| `.docx` | application/vnd.openxmlformats-officedocument.wordprocessingml.document | Large/complex documents |
| `.doc` | application/msword | Large/complex legacy Word |
| `.pptx` | application/vnd.openxmlformats-officedocument.presentationml.presentation | Large presentations |
| `.ppt` | application/vnd.ms-powerpoint | Large legacy PowerPoint |
| `.xlsx` | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | Large spreadsheets |
| `.xls` | application/vnd.ms-excel | Large legacy Excel |

**When Used**:
- Scanned PDFs (little/no text layer)
- Complex PDF layouts (many blocks, images, tables)
- Large Office files (>= 5MB)
- Documents requiring OCR

**Characteristics**:
- Highest quality extraction
- Advanced table recognition
- OCR for scanned content
- Slower but more accurate

### Unsupported File Types

The following file types are **not supported** for extraction:

| Type | Extensions | Reason |
|------|------------|--------|
| Images | `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`, `.heic` | Standalone image files are not processed. Image OCR is only performed within documents (e.g., scanned PDFs) via the Docling engine. |

## Engine Selection Summary

| Document Type | Condition | Engine | Service |
|--------------|-----------|--------|---------|
| PDF | Simple text-based | `fast_pdf` | Local (PyMuPDF) |
| PDF | Scanned or complex | `docling` | Docling service |
| DOCX, PPTX, XLSX | < 5MB | `extraction-service` | Extraction service (MarkItDown) |
| DOCX, PPTX, XLSX | >= 5MB | `docling` | Docling service |
| DOC, PPT, XLS | < 5MB | `extraction-service` | Extraction service (LibreOffice + MarkItDown) |
| DOC, PPT, XLS | >= 5MB | `docling` | Docling service |
| TXT, MD, CSV, HTML | Always | `extraction-service` | Extraction service |
| MSG, EML | Always | `extraction-service` | Extraction service |
| Images | Always | `unsupported` | N/A - standalone images not supported |
| Unknown | Always | `extraction-service` | Extraction service (fallback) |

## Extraction Result Fields

After extraction, the `ExtractionResult` record stores triage decisions:

```python
ExtractionResult {
    # Core fields
    status: "completed"
    extraction_tier: "basic" | "enhanced"  # For backwards compatibility

    # Triage fields (new)
    triage_engine: "fast_pdf" | "extraction-service" | "docling" | "unsupported"
    triage_needs_ocr: bool       # Whether OCR was required
    triage_needs_layout: bool    # Whether complex layout handling was needed
    triage_complexity: "low" | "medium" | "high"
    triage_duration_ms: int      # Time spent in triage phase
}
```

### Tier Mapping

For backwards compatibility, `extraction_tier` is computed from `triage_engine`:

| Triage Engine | Extraction Tier |
|--------------|-----------------|
| `fast_pdf` | `basic` |
| `extraction-service` | `basic` |
| `docling` | `enhanced` |
| `unsupported` | N/A (extraction fails) |

## Stage-by-Stage Processing

### Stage 1: Upload / Ingestion

Documents enter Curatore through multiple sources:

| Source | Endpoint/Trigger | Source Type |
|--------|------------------|-------------|
| Manual Upload | `POST /api/v1/storage/upload/proxy` | `upload` |
| SharePoint Sync | SharePoint sync job | `sharepoint` |
| Web Scraping | Scrape collection crawl | `web_scrape` |
| SAM.gov | SAM pull job | `sam_gov` |

**What Happens**:
1. File uploaded to MinIO (`curatore-uploads` bucket)
2. `Asset` record created with `status=pending`
3. `Run` record created with `run_type=extraction`
4. Extraction task queued to Celery

### Stage 2: Triage

The triage service analyzes the document:

1. Detect file type from extension and MIME type
2. For PDFs: Analyze with PyMuPDF (text layer, complexity)
3. For Office files: Check file size
4. Select optimal engine
5. Record triage decision

**Triage Duration**: Typically < 100ms

### Stage 3: Extraction

The selected engine extracts content:

1. Download file from MinIO
2. Execute engine-specific extraction
3. Convert to Markdown format
4. Upload to `curatore-processed` bucket
5. Update `ExtractionResult` with triage fields

### Stage 4: Search Indexing

After extraction completes:

1. Download extracted Markdown
2. Split into chunks (~1500 chars with 200 char overlap)
3. Generate embeddings via OpenAI API (text-embedding-3-small)
4. Insert into `search_chunks` table (PostgreSQL + pgvector)
5. Set `indexed_at` timestamp on Asset

## Configuration

### Enable/Disable Docling

In `config.yml`:
```yaml
extraction:
  engines:
    - name: docling
      engine_type: docling
      enabled: true  # Set to false to use fast engines only
      service_url: http://docling:8012
```

When Docling is disabled:
- PDFs use `fast_pdf` (may have lower quality for complex documents)
- Large Office files use `extraction-service` instead

### Enable/Disable Search Indexing

```yaml
search:
  enabled: true  # Set to false to disable indexing
```

## Monitoring

### API Response

`GET /api/v1/assets/{id}` returns:
```json
{
  "asset": {
    "id": "...",
    "status": "ready",
    "extraction_tier": "enhanced",
    "indexed_at": "2026-02-01T19:05:00Z"
  },
  "extraction": {
    "status": "completed",
    "extraction_tier": "enhanced",
    "triage_engine": "docling",
    "triage_needs_ocr": true,
    "triage_complexity": "high",
    "triage_duration_ms": 45
  }
}
```

### Frontend Display

The asset detail page shows:
- **Engine**: Badge showing which engine was used (Fast PDF, MarkItDown, Docling, OCR)
- **OCR**: Badge if OCR was used
- **Complexity**: Badge if document was complex
- **Indexed**: Shows "Indexed" with timestamp

### SQL Queries

```sql
-- Assets by extraction engine
SELECT triage_engine, COUNT(*)
FROM extraction_results
WHERE status = 'completed'
GROUP BY triage_engine;

-- Average triage duration by engine
SELECT triage_engine, AVG(triage_duration_ms) as avg_ms
FROM extraction_results
WHERE triage_duration_ms IS NOT NULL
GROUP BY triage_engine;

-- Documents that needed OCR
SELECT a.original_filename, er.triage_engine, er.triage_complexity
FROM extraction_results er
JOIN assets a ON er.asset_id = a.id
WHERE er.triage_needs_ocr = true;
```

## Re-processing

### Trigger Re-extraction

```bash
curl -X POST http://localhost:8000/api/v1/assets/{id}/reextract
```

This creates a new extraction Run and re-processes through triage.

### Bulk Re-extraction

```bash
docker exec curatore-backend python -m app.commands.reextract_all
```

Options:
- `--dry-run`: Show what would be done
- `--limit N`: Process only N assets
- `--batch-size N`: Process in batches of N

### Trigger Search Reindex

```bash
curl -X POST http://localhost:8000/api/v1/search/reindex
```
