# Document Processing Pipeline

This document describes how Curatore processes documents from upload through search indexing.

## Overview

Curatore uses a **tiered extraction system** with:
- **Basic extraction** (fast) using MarkItDown for all files
- **Enhanced extraction** (quality) using Docling for eligible document types
- **Deferred indexing** to avoid duplicate embedding generation

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DOCUMENT PROCESSING PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  ┌──────────┐    ┌───────────────┐    ┌─────────────────┐    ┌──────────────────────┐  │
│  │  UPLOAD  │───▶│   EXTRACTION  │───▶│   ENHANCEMENT   │───▶│      INDEXING        │  │
│  │          │    │    (Basic)    │    │   (Conditional) │    │     (pgvector)       │  │
│  └──────────┘    └───────────────┘    └─────────────────┘    └──────────────────────┘  │
│       │                 │                     │                        │               │
│       │                 │                     │                        │               │
│       ▼                 ▼                     ▼                        ▼               │
│   Asset created     Markdown in          Enhanced                Searchable           │
│   status=pending    MinIO bucket         markdown               in pgvector           │
│                     tier=basic           tier=enhanced           indexed_at set       │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Stage 1: Upload / Ingestion

Documents enter Curatore through multiple sources:

| Source | Endpoint/Trigger | Source Type |
|--------|------------------|-------------|
| Manual Upload | `POST /api/v1/storage/upload/proxy` | `upload` |
| SharePoint Sync | SharePoint sync job | `sharepoint` |
| Web Scraping | Scrape collection crawl | `web_scrape` |
| SAM.gov | SAM pull job | `sam_gov` |

### What Happens
1. File uploaded to MinIO (`curatore-uploads` bucket)
2. `Asset` record created with `status=pending`
3. `Run` record created with `run_type=extraction`
4. `ExtractionResult` record created with `status=pending`
5. Extraction task queued to Celery

### Asset Created State
```
Asset {
    status: "pending"
    extraction_tier: null
    enhancement_eligible: null
    indexed_at: null
}
```

## Stage 2: Basic Extraction

All files go through basic extraction using MarkItDown (via extraction-service).

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BASIC EXTRACTION                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌──────────────┐      ┌─────────────────┐      ┌───────────────┐  │
│   │  Download    │─────▶│   MarkItDown    │─────▶│    Upload     │  │
│   │  from MinIO  │      │   Extraction    │      │   Markdown    │  │
│   └──────────────┘      └─────────────────┘      └───────────────┘  │
│          │                      │                        │          │
│          ▼                      ▼                        ▼          │
│   curatore-uploads       PDF → Markdown          curatore-processed │
│   (raw file)             DOCX → Markdown         (extracted.md)     │
│                          HTML → Markdown                             │
│                          etc.                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Supported File Types (Basic)
- PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS
- HTML, TXT, MD, CSV, JSON, XML
- Images (with OCR if enabled)
- And many more via MarkItDown

### After Basic Extraction
```
Asset {
    status: "ready"
    extraction_tier: "basic"
    enhancement_eligible: true/false  (determined by file type)
    indexed_at: null                   (not yet indexed)
}

ExtractionResult {
    status: "completed"
    extraction_tier: "basic"
    extracted_bucket: "curatore-processed"
    extracted_object_key: "{org}/{path}/filename.md"
}
```

## Stage 3: Enhancement (Conditional)

Enhancement is triggered **only if**:
1. File type is enhancement-eligible
2. Docling service is enabled in config

### Enhancement-Eligible File Types
| Extension | MIME Type | Reason |
|-----------|-----------|--------|
| `.pdf` | application/pdf | Tables, forms, complex layouts |
| `.docx` | application/vnd.openxmlformats-officedocument.wordprocessingml.document | Styles, tables |
| `.doc` | application/msword | Legacy Word documents |
| `.pptx` | application/vnd.openxmlformats-officedocument.presentationml.presentation | Slides, graphics |
| `.ppt` | application/vnd.ms-powerpoint | Legacy PowerPoint |
| `.xlsx` | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | Spreadsheet structure |
| `.xls` | application/vnd.ms-excel | Legacy Excel |

### Non-Eligible File Types
- HTML (already well-structured)
- Plain text, Markdown (no structure to enhance)
- Images (no text structure)
- CSV, JSON, XML (already structured data)

### Enhancement Flow
```
┌─────────────────────────────────────────────────────────────────────┐
│                        ENHANCEMENT DECISION                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│                    Basic Extraction Complete                         │
│                            │                                         │
│                            ▼                                         │
│                  ┌─────────────────────┐                            │
│                  │ Enhancement Eligible?│                            │
│                  │ (PDF, DOCX, etc.)   │                            │
│                  └─────────────────────┘                            │
│                       │           │                                  │
│                      YES          NO                                 │
│                       │           │                                  │
│                       ▼           ▼                                  │
│            ┌─────────────────┐  ┌─────────────────┐                 │
│            │ Docling Enabled? │  │  INDEX NOW     │                 │
│            └─────────────────┘  │  (basic tier)   │                 │
│                 │        │      └─────────────────┘                 │
│                YES       NO                                          │
│                 │        │                                           │
│                 ▼        ▼                                           │
│     ┌─────────────────┐ ┌─────────────────┐                         │
│     │ Queue Enhancement│ │  INDEX NOW     │                         │
│     │ (defer indexing) │ │  (basic tier)   │                         │
│     └─────────────────┘ └─────────────────┘                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Why Defer Indexing?

Generating embeddings is expensive (OpenAI API calls). If we index after basic extraction and then index again after enhancement, we pay twice. By deferring indexing for enhancement-eligible files, we only generate embeddings once with the best available content.

### After Enhancement
```
Asset {
    status: "ready"
    extraction_tier: "enhanced"
    enhancement_eligible: true
    indexed_at: null  (still waiting for indexing)
}

ExtractionResult {
    status: "completed"
    extraction_tier: "enhanced"
    extracted_bucket: "curatore-processed"
    extracted_object_key: "{org}/{path}/filename.md"  (overwritten with enhanced content)
}
```

## Stage 4: Search Indexing

Indexing happens via the `index_asset_task` Celery task.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SEARCH INDEXING                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌───────────────┐    ┌─────────────────┐    ┌──────────────────┐  │
│   │   Download    │───▶│    Chunking     │───▶│    Embedding     │  │
│   │   Markdown    │    │  (~1500 chars)  │    │   Generation     │  │
│   └───────────────┘    └─────────────────┘    └──────────────────┘  │
│          │                     │                       │            │
│          ▼                     ▼                       ▼            │
│   curatore-processed     Split into           OpenAI API call       │
│   (extracted.md)         overlapping          text-embedding-3-small │
│                          chunks               1536 dimensions        │
│                                                                      │
│                          ┌─────────────────┐                        │
│                          │  Insert into    │                        │
│                          │ search_chunks   │                        │
│                          │    table        │                        │
│                          └─────────────────┘                        │
│                                  │                                   │
│                                  ▼                                   │
│                          PostgreSQL + pgvector                       │
│                          (hybrid full-text + semantic search)        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Indexing Trigger Points

| Scenario | Trigger Point |
|----------|---------------|
| Non-eligible file | After basic extraction completes |
| Eligible file, Docling disabled | After basic extraction completes |
| Eligible file, Docling enabled | After enhancement completes |

### After Indexing
```
Asset {
    status: "ready"
    extraction_tier: "basic" or "enhanced"
    enhancement_eligible: true/false
    indexed_at: "2026-02-01T20:00:00Z"  (timestamp set)
}
```

### search_chunks Table Schema
```sql
CREATE TABLE search_chunks (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(50),        -- 'asset', 'sam_notice', 'sam_solicitation'
    source_id UUID,                 -- Asset ID or notice ID
    organization_id UUID,
    chunk_index INTEGER,            -- 0, 1, 2, ... for each chunk
    content TEXT,                   -- Chunk text content
    title VARCHAR(500),
    filename VARCHAR(500),
    url TEXT,
    embedding VECTOR(1536),         -- pgvector embedding
    source_type_filter VARCHAR(50), -- 'upload', 'sharepoint', 'web_scrape', 'sam_gov'
    content_type VARCHAR(255),
    collection_id UUID,             -- For scrape collections
    sync_config_id UUID,            -- For SharePoint syncs
    metadata JSONB,
    UNIQUE(source_type, source_id, chunk_index)
);
```

## Complete Pipeline States

### State Diagram

```
                              UPLOAD
                                │
                                ▼
                    ┌───────────────────────┐
                    │   status: pending     │
                    │   tier: null          │
                    │   eligible: null      │
                    │   indexed_at: null    │
                    └───────────────────────┘
                                │
                        BASIC EXTRACTION
                                │
                                ▼
                    ┌───────────────────────┐
                    │   status: ready       │
                    │   tier: basic         │
                    │   eligible: true/false│
                    │   indexed_at: null    │
                    └───────────────────────┘
                         │              │
              eligible=true &&     eligible=false ||
              docling=enabled      docling=disabled
                         │              │
                         ▼              ▼
              ┌─────────────────┐  ┌─────────────────┐
              │   ENHANCING...  │  │    INDEXING...  │
              │   (Docling)     │  │   (pgvector)    │
              └─────────────────┘  └─────────────────┘
                         │              │
                         ▼              │
              ┌─────────────────┐       │
              │ tier: enhanced  │       │
              │ indexed_at: null│       │
              └─────────────────┘       │
                         │              │
                    INDEXING...         │
                         │              │
                         ▼              ▼
                    ┌───────────────────────┐
                    │   status: ready       │
                    │   tier: basic/enhanced│
                    │   eligible: true/false│
                    │   indexed_at: <time>  │  ← FULLY PROCESSED
                    └───────────────────────┘
```

## Monitoring Pipeline Status

### API Response
`GET /api/v1/assets/{id}` returns:
```json
{
  "asset": {
    "id": "...",
    "status": "ready",
    "extraction_tier": "enhanced",
    "enhancement_eligible": true,
    "enhancement_queued_at": "2026-02-01T19:00:00Z",
    "indexed_at": "2026-02-01T19:05:00Z"
  },
  "extraction": {
    "status": "completed",
    "extraction_tier": "enhanced",
    "extractor_version": "docling-enhancement"
  }
}
```

### Frontend Display
The asset detail page shows a "Processing Pipeline" section with badges:
- **Extracted**: Shows tier (basic/enhanced) or processing state
- **Enhanced**: Shows enhancement status or "N/A" if not eligible
- **Indexed**: Shows "Indexed" with timestamp or "Not Indexed"

### SQL Queries

```sql
-- Find assets not yet indexed
SELECT id, original_filename, extraction_tier, enhancement_eligible
FROM assets
WHERE status = 'ready' AND indexed_at IS NULL;

-- Find enhancement-eligible assets still at basic tier
SELECT id, original_filename
FROM assets
WHERE enhancement_eligible = true
  AND extraction_tier = 'basic'
  AND status = 'ready';

-- Count assets by pipeline state
SELECT
    CASE
        WHEN status = 'pending' THEN 'extracting'
        WHEN indexed_at IS NULL AND enhancement_eligible AND extraction_tier = 'basic' THEN 'awaiting_enhancement'
        WHEN indexed_at IS NULL THEN 'awaiting_indexing'
        ELSE 'complete'
    END as pipeline_state,
    COUNT(*) as count
FROM assets
WHERE status IN ('pending', 'ready')
GROUP BY 1;
```

## Configuration

### Enable/Disable Enhancement
In `config.yml`:
```yaml
extraction:
  engines:
    - name: docling
      engine_type: docling
      enabled: true  # Set to false to disable enhancement
      service_url: http://docling:8012
```

### Enable/Disable Search Indexing
```yaml
search:
  enabled: true  # Set to false to disable all indexing
```

Or via environment variable:
```bash
SEARCH_ENABLED=true
```

## Re-processing

### Trigger Re-extraction
```bash
curl -X POST http://localhost:8000/api/v1/assets/{id}/reextract
```
This creates a new extraction Run and re-processes the asset through the full pipeline.

### Trigger Reindex (all assets)
```bash
curl -X POST http://localhost:8000/api/v1/search/reindex
```

### Manual Reindex (single asset)
```python
from app.services.pg_index_service import pg_index_service
from app.services.database_service import database_service

async with database_service.get_session() as session:
    await pg_index_service.index_asset(session, asset_id)
```
