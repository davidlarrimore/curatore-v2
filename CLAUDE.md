# CLAUDE.md

Development guidance for Claude Code working with Curatore v2.

## Project Overview

Curatore v2 is a document processing and curation platform that converts documents to Markdown, provides full-text search, and supports LLM-powered analysis.

### Tech Stack
- **Backend**: FastAPI (Python 3.12+), Celery workers, SQLAlchemy
- **Frontend**: Next.js 15.5, TypeScript, React 19, Tailwind CSS
- **Services**: Redis, MinIO/S3, Playwright, Extraction Service
- **Database**: PostgreSQL 16 with pgvector (required)

### Architecture Principles
1. **Extraction is infrastructure** - Automatic on upload, not per-workflow
2. **Assets are first-class** - Documents tracked with version history and provenance
3. **Run-based execution** - All processing tracked via Run records with structured logs
4. **Database is source of truth** - Object store contains only bytes
5. **Queue isolation** - Each job type has its own Celery queue to prevent blocking

### Queue Architecture
All background jobs are managed through the Queue Registry system:
- **Queue types defined in code** - See `backend/app/services/queue_registry.py`
- **Celery queues per job type** - Extraction, SAM, Scrape, SharePoint, Maintenance
- **Job Manager UI** - Unified view at `/admin/queue`
- **Configurable throttling** - Set `max_concurrent` per queue in `config.yml`

### Key Data Models
| Model | Purpose |
|-------|---------|
| `Asset` | Document with provenance, version history, and pipeline status |
| `AssetVersion` | Individual versions of an asset |
| `ExtractionResult` | Extracted markdown with triage metadata |
| `Run` | Universal execution tracking (extraction, crawl, sync) |
| `RunGroup` | Parent-child job tracking for group completion |
| `RunLogEvent` | Structured logging for runs |
| `ScrapeCollection` | Web scraping project with seed URLs |
| `SamSearch` | SAM.gov saved search configuration |
| `SamSolicitation` | Groups SAM.gov notices with same solicitation number |
| `SamNotice` | Individual SAM.gov notice (standalone or linked to solicitation) |
| `SharePointSyncConfig` | SharePoint folder sync configuration |
| `ScheduledTask` | Database-backed scheduled maintenance |
| `Procedure` | Reusable workflow definitions (scheduled, event-driven) |
| `Pipeline` | Multi-stage document processing workflows |

### Asset Pipeline Fields
| Field | Type | Description |
|-------|------|-------------|
| `status` | string | pending, ready, failed, deleted |
| `extraction_tier` | string | basic or enhanced (for backwards compatibility) |
| `indexed_at` | datetime | When indexed to pgvector search (null = not indexed) |

### Extraction Result Triage Fields
| Field | Type | Description |
|-------|------|-------------|
| `triage_engine` | string | fast_pdf, extraction-service, docling, or unsupported |
| `triage_needs_ocr` | bool | Whether document required OCR |
| `triage_needs_layout` | bool | Whether complex layout handling was needed |
| `triage_complexity` | string | low, medium, or high |
| `triage_duration_ms` | int | Time spent in triage phase |

---

## Quick Start

```bash
# Start all services
./scripts/dev-up.sh

# Initialize storage buckets
./scripts/init_storage.sh

# Create admin user
docker exec curatore-backend python -m app.commands.seed --create-admin

# View logs
./scripts/dev-logs.sh
```

### URLs
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- MinIO Console: http://localhost:9001
- PostgreSQL: localhost:5432 (curatore/curatore_dev_password)

---

## Development Commands

```bash
# Backend tests
pytest backend/tests -v

# Frontend dev
cd frontend && npm run dev

# Worker logs
./scripts/tail_worker.sh

# Queue health
./scripts/queue_health.sh
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/v1/routers/     # API endpoints
│   ├── services/           # Business logic
│   ├── database/
│   │   ├── models.py       # SQLAlchemy models
│   │   └── procedures.py   # Procedure/Pipeline models
│   ├── functions/          # Function library (llm, search, output, etc.)
│   ├── procedures/         # Procedure executor and YAML definitions
│   ├── pipelines/          # Pipeline executor and YAML definitions
│   └── tasks.py            # Celery tasks
├── alembic/                # Database migrations

frontend/
├── app/                    # Next.js App Router pages
│   └── admin/
│       ├── functions/      # Function browser
│       ├── procedures/     # Procedure management
│       └── pipelines/      # Pipeline management
├── components/             # React components
└── lib/
    ├── api.ts                    # API client
    ├── unified-jobs-context.tsx  # WebSocket-based job tracking
    ├── websocket-client.ts       # WebSocket client with reconnection
    ├── context-shims.ts          # Backward-compatible hooks
    └── job-type-config.ts        # Job type configuration

extraction-service/         # Document conversion microservice
playwright-service/         # Browser rendering microservice
```

---

## Core Services

### Backend Services (`backend/app/services/`)

| Service | Purpose |
|---------|---------|
| `asset_service.py` | Asset CRUD and version management |
| `run_service.py` | Run execution tracking |
| `run_group_service.py` | Parent-child job tracking for group completion |
| `event_service.py` | Event emission for triggering procedures/pipelines |
| `extraction_orchestrator.py` | Extraction coordination |
| `extraction_queue_service.py` | Extraction queue throttling and management |
| `queue_registry.py` | Queue type definitions and capabilities |
| `pg_search_service.py` | Hybrid full-text + semantic search (PostgreSQL + pgvector) |
| `pg_index_service.py` | Document chunking, embedding, and indexing |
| `embedding_service.py` | Embedding generation via OpenAI API (text-embedding-3-small) |
| `chunking_service.py` | Document splitting for search |
| `minio_service.py` | Object storage operations |
| `sam_service.py` | SAM.gov API integration |
| `scrape_service.py` | Web scraping collections |
| `scheduled_task_service.py` | Scheduled maintenance |
| `auth_service.py` | JWT/API key authentication |
| `connection_service.py` | Runtime service connections |

### Key Routers (`backend/app/api/v1/routers/`)

| Router | Endpoints |
|--------|-----------|
| `assets.py` | Asset CRUD, versions, re-extraction, pipeline status |
| `runs.py` | Run status, logs, retry, group status |
| `queue_admin.py` | Job Manager: queue registry, active jobs, cancel |
| `search.py` | Full-text + semantic search with facets |
| `sam.py` | SAM.gov searches, solicitations, notices |
| `scrape.py` | Web scraping collections |
| `sharepoint_sync.py` | SharePoint folder sync configuration and triggers |
| `storage.py` | File upload/download |
| `scheduled_tasks.py` | Maintenance task admin |
| `functions.py` | Function browser and direct execution |
| `procedures.py` | Procedure CRUD, triggers, execution |
| `pipelines.py` | Pipeline CRUD, triggers, runs, item states |
| `webhooks.py` | Webhook triggers for procedures/pipelines |

---

## SAM.gov Data Model

Curatore integrates with SAM.gov (System for Award Management) to track federal contracting opportunities. Understanding the data model is critical for working with SAM.gov features.

### Key Concept: Notices vs Solicitations

**SAM.gov API returns Notices, not Solicitations.** A "notice" is the fundamental unit from the SAM.gov API - it represents a single posting (opportunity, amendment, special notice, etc.).

**Solicitations are our abstraction.** When a notice has a `solicitation_number`, we create a `SamSolicitation` record to group related notices together. Multiple notices (original + amendments) can belong to the same solicitation.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SAM.GOV DATA MODEL                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

  SAM.gov API                    Curatore Database
      │
      ▼
┌─────────────┐
│   Notice    │─────────┐
│ (has solnum)│         │
└─────────────┘         │     ┌─────────────────┐
                        ├────▶│  SamSolicitation │◀──── Groups notices with same solnum
┌─────────────┐         │     │  (our grouping)  │
│   Notice    │─────────┘     └─────────────────┘
│ (amendment) │                        │
└─────────────┘                        │
                                       ▼
┌─────────────┐               ┌─────────────────┐
│   Notice    │──────────────▶│   SamNotice     │◀──── Each notice becomes a SamNotice
│ (Special)   │               │  solicitation_id│       - With solnum: linked to solicitation
└─────────────┘               │  = NULL for     │       - Without solnum: standalone
  No solnum!                  │  standalone     │
                              └─────────────────┘
```

### Notice Types (ptype codes from SAM.gov API)

| Type Code | Name | Has Solicitation Number? |
|-----------|------|-------------------------|
| `o` | Solicitation | Yes (usually) |
| `p` | Presolicitation | Yes (usually) |
| `k` | Combined Synopsis/Solicitation | Yes (usually) |
| `r` | Sources Sought | Maybe |
| `s` | Special Notice | **No** - always standalone |
| `g` | Sale of Surplus Property | Maybe |
| `a` | Award Notice | Yes (usually) |
| `u` | Justification (J&A) | Yes (usually) |
| `i` | Intent to Bundle | Maybe |

### Standalone Notices

**Special Notices (type "s")** are informational and don't have solicitation numbers. They are stored as:
- `SamNotice` with `solicitation_id = NULL`
- `organization_id` set on the notice itself (not inherited from solicitation)
- Agency info stored directly on the notice (`agency_name`, `bureau_name`, `office_name`)
- Attachments linked to notice via `notice_id` (not `solicitation_id`)

### Storage Paths

```
# Solicitation-linked attachments
{org_id}/sam/{agency}/{bureau}/solicitations/{sol_number}/attachments/{filename}

# Standalone notice attachments
{org_id}/sam/{agency}/{bureau}/notices/{notice_id}/attachments/{filename}
```

### Database Models

| Model | Purpose |
|-------|---------|
| `SamSearch` | Saved search configuration (NAICS codes, PSC codes, departments, etc.) |
| `SamSolicitation` | Groups related notices with same solicitation_number |
| `SamNotice` | Individual notice from SAM.gov (can be standalone or linked to solicitation) |
| `SamAttachment` | File attachment (linked to solicitation and/or notice) |
| `SamAgency` / `SamSubAgency` | Agency hierarchy cache |

### Key Service Files

| File | Purpose |
|------|---------|
| `sam_service.py` | Database operations for SAM entities |
| `sam_pull_service.py` | SAM.gov API integration and data sync |
| `sam_api_usage_service.py` | Rate limiting and API quota tracking |
| `sam_summarization_service.py` | LLM-powered summary generation |

---

## Document Processing Pipeline

Curatore uses an intelligent **triage-based extraction system** that analyzes documents before extraction to route them to the optimal engine.

### Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           DOCUMENT PROCESSING PIPELINE                           │
└─────────────────────────────────────────────────────────────────────────────────┘

     UPLOAD/SYNC                     TRIAGE                    EXTRACTION              INDEXING
         │                              │                          │                       │
         ▼                              ▼                          ▼                       ▼
┌─────────────────┐           ┌─────────────────┐         ┌─────────────────┐    ┌─────────────────┐
│  Asset Created  │──────────▶│  Analyze Doc    │────────▶│  Route to       │───▶│  Search Index   │
│    (pending)    │           │  Select Engine  │         │  Optimal Engine │    │   (pgvector)    │
└─────────────────┘           └─────────────────┘         └─────────────────┘    └─────────────────┘
         │                         (< 100ms)                      │                       │
         │                              │                         ▼                       ▼
         │                    ┌─────────┴─────────┐      triage_engine set        indexed_at set
         │                    ▼                   ▼
         │              Simple docs         Complex docs
         │              (fast_pdf,          (docling,
         │               extraction-         ocr_only)
         │               service)
         │
         └──────────────── Run + RunLogEvent tracking ─────────────┘
```

### Triage-Based Engine Selection

The triage service analyzes each document and selects the optimal extraction engine:

| Engine | When Used | Supported Extensions |
|--------|-----------|---------------------|
| `fast_pdf` | Simple text-based PDFs | `.pdf` |
| `extraction-service` | Office files, text, emails, HTML | `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.xlsb`, `.txt`, `.md`, `.csv`, `.html`, `.htm`, `.xml`, `.json`, `.msg`, `.eml` |
| `docling` | Complex/scanned PDFs, large Office files | `.pdf` (complex), `.docx/.pptx/.xlsx` (>5MB) |
| `unsupported` | Standalone image files | `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`, `.heic` |

**Note:** Standalone image files are NOT supported. Image OCR is only performed within documents (e.g., scanned PDFs) via the Docling engine.

### Triage Decision Logic

**For PDFs** (analyzed with PyMuPDF):
- Text per page < 100 chars → needs OCR → `docling`
- Blocks per page > 50 → complex layout → `docling`
- Images per page > 3 → image-heavy → `docling`
- Otherwise → simple text → `fast_pdf`

**For Office files**:
- File size < 5MB → `extraction-service` (MarkItDown)
- File size >= 5MB → `docling` (better layout handling)

**For text files/emails/HTML**: Always → `extraction-service`

**For images**: `unsupported` (standalone images not processed)

### Extraction Result Fields

```python
class ExtractionResult:
    status: str                    # pending, completed, failed
    extraction_tier: str           # basic, enhanced (for backwards compat)

    # Triage fields
    triage_engine: str             # fast_pdf, extraction-service, docling, unsupported
    triage_needs_ocr: bool         # Whether OCR was required
    triage_needs_layout: bool      # Whether complex layout handling was needed
    triage_complexity: str         # low, medium, high
    triage_duration_ms: int        # Time spent in triage phase
```

### Frontend Pipeline Status Display

The asset detail page (`/assets/{id}`) shows:
- **Engine badge**: Fast PDF, MarkItDown, Docling, or OCR
- **OCR badge**: If OCR was used
- **Complexity badge**: If document was complex
- **Indexed badge**: With timestamp

### Key Services

| Service | Purpose |
|---------|---------|
| `triage_service.py` | Analyzes documents and selects optimal engine |
| `extraction_orchestrator.py` | Coordinates triage and extraction |
| `extraction/fast_pdf.py` | PyMuPDF-based extraction for simple PDFs |
| `extraction/extraction_service.py` | MarkItDown for Office/text files |
| `pg_index_service.py` | Chunks content, generates embeddings, indexes to PostgreSQL |

For detailed documentation, see [`docs/DOCUMENT_PROCESSING.md`](docs/DOCUMENT_PROCESSING.md).

---

## Search Architecture

Curatore uses PostgreSQL with pgvector for hybrid full-text + semantic search:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SEARCH ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────┐
                    │    Search Query     │
                    └──────────┬──────────┘
                               │
                               ▼
              ┌────────────────────────────────┐
              │      pg_search_service.py      │
              │   (Hybrid Search Orchestrator) │
              └────────────────────────────────┘
                       │              │
          ┌────────────┘              └────────────┐
          ▼                                        ▼
┌──────────────────────┐               ┌──────────────────────┐
│   Full-Text Search   │               │   Semantic Search    │
│  (PostgreSQL tsvector)│               │  (pgvector cosine)   │
│                      │               │                      │
│  • GIN indexes       │               │  • 1536-dim vectors  │
│  • Keyword matching  │               │  • OpenAI embeddings │
│  • ts_rank scoring   │               │  • Similarity search │
└──────────────────────┘               └──────────────────────┘
          │                                        │
          └────────────┐              ┌────────────┘
                       ▼              ▼
              ┌────────────────────────────────┐
              │       Hybrid Scoring           │
              │  (configurable weighting)      │
              │                                │
              │  score = α×keyword + β×semantic │
              └────────────────────────────────┘
                               │
                               ▼
              ┌────────────────────────────────┐
              │       search_chunks table      │
              │                                │
              │  • source_type (asset, sam)    │
              │  • source_id                   │
              │  • chunk_index                 │
              │  • content (text)              │
              │  • embedding (vector)          │
              │  • metadata (JSONB)            │
              └────────────────────────────────┘
```

### Search Features
- **Full-text search**: PostgreSQL tsvector + GIN indexes for keyword matching
- **Semantic search**: pgvector embeddings (1536-dim via OpenAI text-embedding-3-small)
- **Hybrid mode**: Combines keyword and semantic scores (configurable weighting)
- **Chunking**: Documents split into ~1500 char chunks with 200 char overlap
- **No external service**: Uses same PostgreSQL database (no Elasticsearch/OpenSearch)
- **Configurable**: Embedding model set in `config.yml` under `llm.models.embedding`

---

## Procedures & Pipelines Framework

Curatore includes a framework for schedulable, event-driven workflows that search content, apply business rules, and execute actions.

### Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     PROCEDURES & PIPELINES FRAMEWORK                             │
└─────────────────────────────────────────────────────────────────────────────────┘

  TRIGGERS                    WORKFLOWS                     OUTPUTS
      │                           │                            │
      ▼                           ▼                            ▼
┌─────────────┐           ┌─────────────┐            ┌─────────────────┐
│   Schedule  │──────────▶│  PROCEDURE  │───────────▶│  LLM Analysis   │
│   (cron)    │           │  (steps)    │            │  Notifications  │
├─────────────┤           └─────────────┘            │  Artifacts      │
│   Event     │                                      └─────────────────┘
│   (system)  │──────────▶┌─────────────┐
├─────────────┤           │  PIPELINE   │───────────▶┌─────────────────┐
│   Webhook   │           │  (stages)   │            │  Enriched Data  │
│   (HTTP)    │──────────▶│  [items]    │            │  Classifications│
└─────────────┘           └─────────────┘            │  Updated Assets │
                                                     └─────────────────┘
```

### Procedures vs Pipelines

| Feature | Procedure | Pipeline |
|---------|-----------|----------|
| Purpose | Execute workflow steps | Process collections of items |
| Structure | Sequential steps | Multi-stage with item tracking |
| Item State | None | Per-item status and checkpoints |
| Use Cases | Digests, notifications, reports | Document classification, enrichment |

### Functions

Functions are the atomic units of work. Located in `backend/app/functions/`:

| Category | Functions |
|----------|-----------|
| `llm` | `generate`, `extract`, `summarize`, `classify` |
| `search` | `search_assets`, `query_solicitations`, `get_content` |
| `output` | `update_metadata`, `bulk_update_metadata`, `create_artifact`, `create_pdf` |
| `notify` | `send_email`, `webhook` |
| `compound` | `analyze_solicitation`, `summarize_solicitations`, `generate_digest` |

### YAML Definitions

Procedures and pipelines are defined in YAML with Jinja2 templating:

```yaml
# backend/app/procedures/definitions/sam_weekly_digest.yaml
name: SAM.gov Weekly Digest
slug: sam_weekly_digest

triggers:
  - type: cron
    cron_expression: "0 18 * * 0"  # Sunday 6 PM
  - type: event
    event_name: sam_pull.completed

steps:
  - name: query_opportunities
    function: query_solicitations
    params:
      posted_within_days: "{{ params.posted_within_days }}"
  - name: generate_digest
    function: generate
    params:
      prompt: "Create digest for {{ steps.query_opportunities | length }} opportunities"
```

### Event System

Events trigger procedures and pipelines:

| Event | Trigger |
|-------|---------|
| `sam_pull.completed` | After SAM.gov pull finishes |
| `sharepoint_sync.completed` | After SharePoint sync finishes |
| `sam_pull.group_completed` | After all extractions from a SAM pull complete |
| `sharepoint_sync.group_completed` | After all extractions from a sync complete |

### Key Files

```
backend/app/
├── functions/
│   ├── base.py              # BaseFunction, FunctionResult
│   ├── context.py           # FunctionContext with services
│   ├── registry.py          # FunctionRegistry
│   └── llm/, search/, output/, notify/, compound/
├── procedures/
│   ├── executor.py          # ProcedureExecutor
│   ├── loader.py            # YAML loader with Jinja2
│   └── definitions/         # YAML procedure definitions
├── pipelines/
│   ├── executor.py          # PipelineExecutor with checkpoints
│   └── definitions/         # YAML pipeline definitions
├── database/
│   └── procedures.py        # Procedure, Pipeline, Trigger models
└── services/
    └── event_service.py     # Event emission
```

### Frontend Pages

| Page | Path | Purpose |
|------|------|---------|
| Functions | `/admin/functions` | Browse and test functions |
| Procedures | `/admin/procedures` | Manage and run procedures |
| Pipelines | `/admin/pipelines` | Manage pipelines and view runs |

---

## Data Flow

### High-Level Flow
```
Upload → Asset Created → Triage → Extraction → Indexing → Search Ready
                           ↓          ↓
                   Select Engine   Run (tracks execution)
                                       ↓
                                  RunLogEvent (structured logs)
```

### Processing Workflow
1. **Upload**: `POST /api/v1/storage/upload/proxy` creates Asset, triggers extraction
2. **Triage**: Analyzes document to select optimal extraction engine (< 100ms)
3. **Extraction**: Routes to selected engine (fast_pdf, extraction-service, or docling)
4. **Indexing**: Chunks content, generates embeddings, indexes to `search_chunks`
5. **Access**: `GET /api/v1/assets/{id}` returns asset with extraction_result and triage metadata

---

## Object Storage Structure

```
curatore-uploads/{org_id}/
├── uploads/{asset_uuid}/{filename}      # File uploads
├── scrape/{collection}/pages/           # Scraped web pages
├── scrape/{collection}/documents/       # Downloaded documents
├── sharepoint/{site}/{path}/            # SharePoint files
└── sam/
    ├── {agency}/{bureau}/solicitations/{number}/attachments/  # Solicitation attachments
    └── {agency}/{bureau}/notices/{notice_id}/attachments/     # Standalone notice attachments

curatore-processed/{org_id}/             # Extracted markdown (mirrors structure)
curatore-temp/{org_id}/                  # Temporary files
```

---

## Adding Features

### New API Endpoint
1. Create router in `backend/app/api/v1/routers/`
2. Add Pydantic models to `backend/app/api/v1/models.py`
3. Implement service in `backend/app/services/`
4. Register router in `backend/app/api/v1/__init__.py`
5. Update `frontend/lib/api.ts`

### New Celery Task
1. Add task to `backend/app/tasks.py`
2. Use `@celery_app.task(name="app.tasks.my_task")`
3. Create Run record for tracking if needed

### New Scheduled Task
1. Add handler to `backend/app/services/maintenance_handlers.py`
2. Register in `MAINTENANCE_HANDLERS` dict
3. Seed task via `python -m app.commands.seed --seed-scheduled-tasks`

### New Queue Type (for background job processing)

The Queue Registry (`backend/app/services/queue_registry.py`) defines all job queue types programmatically. Each queue type has its own Celery queue for isolation and configurable capabilities.

**Existing Queue Types:**
| Queue | Run Type | Celery Queue | Capabilities |
|-------|----------|--------------|--------------|
| Extraction | `extraction` | `extraction` | cancel, retry |
| SAM.gov | `sam_pull` | `sam` | - |
| Web Scrape | `scrape` | `scrape` | cancel |
| SharePoint | `sharepoint_sync` | `sharepoint` | cancel |
| Maintenance | `system_maintenance` | `maintenance` | - |
| Procedure | `procedure` | `maintenance` | cancel, retry |
| Pipeline | `pipeline` | `pipeline` | cancel, retry |

**To add a new queue type (e.g., Google Drive sync):**

1. **Define the queue class** in `backend/app/services/queue_registry.py`:
```python
class GoogleDriveQueue(QueueDefinition):
    """Google Drive document synchronization queue."""

    def __init__(self):
        super().__init__(
            queue_type="google_drive",           # Unique identifier
            celery_queue="google_drive",         # Celery queue name
            run_type_aliases=["gdrive_sync"],    # Alternative run_type values
            can_cancel=True,                     # Allow job cancellation
            can_retry=False,                     # No automatic retry
            label="Google Drive",                # UI display name
            description="Google Drive sync",     # UI description
            icon="cloud",                        # Lucide icon name
            color="blue",                        # Tailwind color
            default_max_concurrent=None,         # None = unlimited
            default_timeout_seconds=1800,        # 30 minutes
        )
```

2. **Register the queue** in `_register_defaults()`:
```python
def _register_defaults(self):
    self.register(ExtractionQueue())
    self.register(SamQueue())
    # ... existing queues ...
    self.register(GoogleDriveQueue())  # Add here
```

3. **Add Celery queue** in `backend/app/celery_app.py`:
```python
app.conf.task_queues = (
    # ... existing queues ...
    Queue("google_drive", routing_key="google_drive"),
)
```

4. **Route tasks** in `celery_app.py`:
```python
task_routes = {
    # ... existing routes ...
    "app.tasks.google_drive_sync_task": {"queue": "google_drive"},
}
```

5. **Update docker-compose.yml** worker command to consume the new queue:
```yaml
# Single worker handles all queues
celery -A app.celery_app worker -Q processing_priority,extraction,sam,scrape,sharepoint,google_drive,maintenance
```

**Note:** All queues are consumed by a single worker container (`curatore-worker`). Queue isolation is achieved through Celery queue routing, not separate worker containers.

6. **Create the task** in `backend/app/tasks.py`:
```python
@celery_app.task(name="app.tasks.google_drive_sync_task")
def google_drive_sync_task(run_id: str, ...):
    # Task implementation
    pass
```

The Job Manager UI (`/admin/queue`) will automatically display the new queue type with its configured capabilities.

**Runtime Configuration (optional):**
Override queue parameters in `config.yml`:
```yaml
queues:
  google_drive:
    max_concurrent: 2        # Limit concurrent syncs
    timeout_seconds: 3600    # Override timeout
```

### Async Deletion Pattern

For resource-intensive deletion operations that may take time (e.g., deleting SharePoint sync configs with many files), use the async deletion pattern:

**Architecture:**
```
User clicks Delete → Confirmation Dialog → POST /delete
                                                ↓
                                    ┌─────────────────────┐
                                    │ Set status=deleting │
                                    │ Create Run record   │
                                    │ Queue Celery task   │
                                    │ Return run_id       │
                                    └─────────────────────┘
                                                ↓
                                    ┌─────────────────────┐
                                    │ Redirect to list    │
                                    │ Show "Deleting..."  │
                                    └─────────────────────┘
                                                ↓
                                    ┌─────────────────────┐
                                    │ UnifiedJobsProvider │
                                    │ WebSocket updates   │
                                    │ Shows toast on done │
                                    └─────────────────────┘
```

**Backend Implementation:**
1. **Endpoint** returns immediately with `run_id`:
```python
@router.delete("/configs/{config_id}")
async def delete_config(...):
    config.status = "deleting"
    run = await run_service.create_run(run_type="xxx_delete", ...)
    my_delete_task.delay(config_id, run_id)
    return {"run_id": str(run.id), "status": "deleting"}
```

2. **Celery task** performs cleanup with progress tracking:
```python
@shared_task
def my_delete_task(config_id, run_id):
    # Update run status, log progress, perform cleanup
    # Mark run completed/failed when done
```

**Frontend Implementation:**
1. Use `useDeletionJobs()` hook from context-shims (wraps unified context):
```tsx
import { useDeletionJobs } from '@/lib/context-shims'

const { addJob, isDeleting } = useDeletionJobs()

const handleDelete = async () => {
  const { run_id } = await api.deleteConfig(id)
  addJob({ runId: run_id, configId: id, configName: name, configType: 'sharepoint' })
  router.push('/list')  // Redirect immediately
}
```

2. Show "Deleting..." state in list views:
```tsx
{config.status === 'deleting' || isDeleting(config.id) ? (
  <Badge>Deleting...</Badge>
) : ...}
```

**Key Files:**
- `backend/app/tasks.py` - `async_delete_sync_config_task`
- `frontend/lib/unified-jobs-context.tsx` - Global job tracking with WebSocket
- `frontend/lib/context-shims.ts` - Backward-compatible hooks
- `frontend/components/ui/ConfirmDeleteDialog.tsx` - Reusable dialog

### Parent-Child Job Pattern (Run Groups)

For parent jobs that spawn child jobs (e.g., SAM pull creates extraction jobs for attachments), use Run Groups to track completion of all children before triggering follow-up procedures:

**Architecture:**
```
Parent Job (SAM Pull) → Creates Run Group → Downloads Attachments
                                                   ↓
                                         Creates Assets (with group_id)
                                                   ↓
                                         Queues Extractions (children linked to group)
                                                   ↓
                                   Each child extraction notifies group on complete/fail
                                                   ↓
                                   When all children done → Group completes
                                                   ↓
                                   Emits {group_type}.group_completed event
                                                   ↓
                                   Triggers configured after_procedure_slug
```

**Supported Group Types:**
| Type | Description | Parent Job | Priority |
|------|-------------|------------|----------|
| `sharepoint_sync` | SharePoint sync + file extractions | SharePoint sync task | 0 (lowest) |
| `sam_pull` | SAM.gov pull + attachment extractions | SAM pull task | 1 |
| `scrape` | Web crawl + document extractions | Scrape task | 1 |
| `pipeline` | Pipeline workflow extractions | Pipeline task | 2 |
| `upload_group` | Grouped uploads + extractions | Bulk upload | 3 |

**Queue Priority System:**

Child extractions spawned by parent jobs are automatically assigned priority based on `group_type`:
```python
# QueuePriority levels (in backend/app/services/queue_registry.py)
SHAREPOINT_SYNC = 0  # Background SharePoint sync extractions (lowest)
SAM_SCRAPE = 1       # SAM.gov and web scrape extractions
PIPELINE = 2         # Pipeline/workflow extractions
USER_UPLOAD = 3      # Direct user uploads (default for new runs)
USER_BOOSTED = 4     # Manually boosted by user (highest)
```

Priority is auto-determined when `group_id` is passed to `asset_service.create_asset()`.

**Timeout Handling:**

Parent jobs are excluded from timeout checks while they have active children:
- Parent jobs with `is_group_parent=True` are not timed out while `completed_children + failed_children < total_children`
- This prevents parent jobs from timing out while waiting for child extractions in queue

**Cancellation Behavior:**

Different job types have different cancellation cascade behavior:

| Job Type | Cascade Mode | Behavior |
|----------|--------------|----------|
| SharePoint Sync | `QUEUED_ONLY` | Cancel pending/submitted children only; running extractions complete |
| SAM.gov Pull | `QUEUED_ONLY` | Cancel pending/submitted children only; running extractions complete |
| Web Scrape | `QUEUED_ONLY` | Cancel pending/submitted children only; running extractions complete |
| Pipeline | `ALL` | Cancel ALL children including running (atomicity - partial results useless) |

Use `job_cancellation_service` for cascade cancellation:
```python
from .services.job_cancellation_service import job_cancellation_service

result = await job_cancellation_service.cancel_parent_job(
    session=session,
    run_id=run_id,
    reason="User cancelled",
)
# Returns: {"success": True, "children_cancelled": 5, "children_skipped": 2}
```

**Failure Handling:**

When a parent job fails:
1. The RunGroup is marked as failed (prevents post-job triggers from running)
2. No new children can be spawned (`should_spawn_children()` returns False)
3. For pipelines: all active children are cancelled
4. For other types: running children complete normally

```python
# In parent task error handler:
await run_group_service.mark_group_failed(session, group_id, str(error))
```

**Backend Implementation:**

1. **Parent job creates group:**
```python
from .services.run_group_service import run_group_service

group = await run_group_service.create_group(
    session=session,
    organization_id=org_id,
    group_type="sam_pull",
    parent_run_id=run_id,
    config={
        "after_procedure_slug": "sam-weekly-digest",
        "after_procedure_params": {},
    },
)
```

2. **Pass group_id when creating assets:**
```python
asset = await asset_service.create_asset(
    session=session,
    # ... other params ...
    group_id=group.id,  # Links child extraction to group with auto-priority
)
```

3. **Extraction orchestrator auto-notifies group:**
The extraction orchestrator automatically calls `run_group_service.child_completed()` or `child_failed()` when extractions finish (no additional code needed).

4. **Finalize group after parent job completes:**
```python
await run_group_service.finalize_group(session, group.id)
```

5. **Handle parent job failure:**
```python
try:
    # ... parent job work ...
except Exception as e:
    await run_group_service.mark_group_failed(session, group_id, str(e))
    raise
```

**Key Files:**
- `backend/app/services/run_group_service.py` - Group lifecycle management
- `backend/app/services/job_cancellation_service.py` - Cascade cancellation logic
- `backend/app/services/extraction_queue_service.py` - Priority handling, timeout exclusion
- `backend/app/services/queue_registry.py` - QueuePriority enum
- `backend/app/database/models.py` - `RunGroup` model, `Run.group_id`, `Run.spawned_by_parent`
- `backend/app/services/extraction_orchestrator.py` - Auto-notifies group

**Frontend Integration:**

The Job Manager UI (`/admin/queue`) displays:
- Parent job badge with "Parent" indicator
- Child job stats showing running/pending/completed/failed counts
- Child job badge for jobs that belong to a parent group

**Automation Configuration:**

Jobs can be configured with `automation_config` JSONB field (e.g., `SamSearch.automation_config`):
```json
{
  "after_procedure_slug": "sam-weekly-digest",
  "after_procedure_params": {
    "include_summaries": true
  }
}
```

---

## Database Configuration

Curatore v2 requires PostgreSQL 16 as the database backend. The Docker setup includes a PostgreSQL container by default.

### Default Configuration (Docker)

PostgreSQL is enabled by default via Docker Compose profile:

```bash
# .env
ENABLE_POSTGRES_SERVICE=true  # Set to false to use external PostgreSQL
POSTGRES_DB=curatore
POSTGRES_USER=curatore
POSTGRES_PASSWORD=curatore_dev_password
DATABASE_URL=postgresql+asyncpg://curatore:curatore_dev_password@postgres:5432/curatore
```

### Connection Pooling

Connection pooling is optimized for PostgreSQL with configurable parameters:

```bash
# .env (optional - defaults shown)
DB_POOL_SIZE=20          # Number of connections to maintain
DB_MAX_OVERFLOW=40       # Extra connections during peak load
DB_POOL_RECYCLE=3600     # Recycle connections after N seconds
```

### Using External PostgreSQL

To use an external PostgreSQL database instead of the Docker container:

1. Set `ENABLE_POSTGRES_SERVICE=false` in `.env`
2. Update `DATABASE_URL` to point to your PostgreSQL instance:
   ```bash
   DATABASE_URL=postgresql+asyncpg://user:password@your-host:5432/curatore
   ```
3. Ensure the database exists and the user has appropriate permissions
4. Run `docker exec curatore-backend python -c "from app.services.database_service import database_service; import asyncio; asyncio.run(database_service.init_db())"` to create tables

### Database Initialization

```bash
# Create tables (if not using migrations)
docker exec curatore-backend python -c "
from app.services.database_service import database_service
import asyncio
asyncio.run(database_service.init_db())
"

# Seed admin user and scheduled tasks
docker exec curatore-backend python -m app.commands.seed --create-admin
```

---

## Configuration

### Key Environment Variables

```bash
# Database (Required)
ENABLE_POSTGRES_SERVICE=true
DATABASE_URL=postgresql+asyncpg://curatore:curatore_dev_password@postgres:5432/curatore

# Object Storage (Required)
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# Optional Services
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
SEARCH_ENABLED=true
SAM_API_KEY=your_key
ENABLE_AUTH=false
ENABLE_DOCLING_SERVICE=false
```

### YAML Configuration (Recommended)
See `config.yml.example`. Use `${VAR_NAME}` to reference secrets from `.env`.

```bash
cp config.yml.example config.yml
python -m app.commands.validate_config
```

---

## Frontend Patterns

### Design System Reference
See `frontend/app/connections/page.tsx` as reference implementation.

**Colors**: Indigo/purple primary, emerald success, red error, amber warning

**Layout**:
```tsx
<div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    {/* Content */}
  </div>
</div>
```

**Icons**: Use Lucide React (`lucide-react`)

**Dark Mode**: All components use `dark:` prefix

### Real-Time Job Tracking (WebSocket)

Curatore uses WebSocket for real-time job status updates with automatic fallback to polling.

**Architecture:**
```
┌─────────────────┐     ┌─────────────────────────────────────────────┐
│   Frontend      │     │                 Backend                      │
│                 │     │                                              │
│ UnifiedJobs     │◀────┼──  WebSocket (/api/v1/ws/jobs)              │
│   Context       │     │       ▲                                      │
│                 │     │       │                                      │
│ StatusBar shows │     │  Redis Pub/Sub  ◀── run_service updates     │
│ connection state│     │                                              │
└─────────────────┘     └──────────────────────────────────────────────┘
```

**Connection States** (shown in StatusBar):
- **Live** (green) - WebSocket connected, real-time updates
- **Polling** (amber) - Fallback mode, polling every 5-10 seconds
- **Reconnecting** (amber) - Attempting to reconnect
- **Offline** (red) - Disconnected

**Usage - Track Jobs:**
```tsx
import { useActiveJobs } from '@/lib/context-shims'
import { RunningJobBanner } from '@/components/ui/RunningJobBanner'

function MyPage() {
  const { addJob, getJobsForResource, isResourceBusy } = useActiveJobs()

  // Start tracking a job
  const handleStart = async () => {
    const result = await api.startJob(resourceId)
    addJob({
      runId: result.run_id,
      jobType: 'sharepoint_sync',
      displayName: 'My Sync',
      resourceId: resourceId,
      resourceType: 'sharepoint_config',
    })
  }

  // Show banners for active jobs
  return (
    <>
      {getJobsForResource('sharepoint_config', resourceId).map(job => (
        <RunningJobBanner key={job.runId} job={job} showChildJobs />
      ))}
    </>
  )
}
```

**Usage - Direct Access to Unified Context:**
```tsx
import { useUnifiedJobs } from '@/lib/unified-jobs-context'

function MyComponent() {
  const {
    jobs,              // All tracked jobs
    queueStats,        // Queue statistics
    connectionStatus,  // 'connected' | 'polling' | 'disconnected' | etc.
    addJob,
    removeJob,
  } = useUnifiedJobs()
}
```

**Key Files:**
- `frontend/lib/unified-jobs-context.tsx` - WebSocket-based job tracking
- `frontend/lib/websocket-client.ts` - WebSocket client with reconnection
- `frontend/lib/context-shims.ts` - Backward-compatible hooks (`useActiveJobs`, `useDeletionJobs`, `useQueue`)
- `frontend/lib/job-type-config.ts` - Job type icons, colors, labels
- `frontend/components/ui/RunningJobBanner.tsx` - Reusable job banner
- `frontend/components/ui/ConnectionStatusIndicator.tsx` - Connection state display
- `backend/app/api/v1/routers/websocket.py` - WebSocket endpoint
- `backend/app/services/pubsub_service.py` - Redis pub/sub for broadcasting

---

## API Quick Reference

### Core Endpoints

```
Assets:
  GET    /api/v1/assets                    # List assets
  GET    /api/v1/assets/{id}               # Get asset with extraction
  POST   /api/v1/assets/{id}/reextract     # Re-run extraction

Runs:
  GET    /api/v1/runs                      # List runs
  GET    /api/v1/runs/{id}/logs            # Get run logs

Search:
  POST   /api/v1/search                    # Full-text search with facets
  GET    /api/v1/search/stats              # Index statistics

Storage:
  POST   /api/v1/storage/upload/proxy      # Upload file
  GET    /api/v1/storage/object/download   # Download file

SAM.gov:
  GET    /api/v1/sam/searches              # List searches
  POST   /api/v1/sam/searches/{id}/pull    # Pull from SAM.gov
  GET    /api/v1/sam/solicitations         # List solicitations

Web Scraping:
  POST   /api/v1/scrape/collections        # Create collection
  POST   /api/v1/scrape/collections/{id}/crawl  # Start crawl

Job Manager (Queue Admin):
  GET    /api/v1/queue/registry               # Get queue type definitions
  GET    /api/v1/queue/jobs                   # List all active jobs
  GET    /api/v1/queue/jobs?run_type=X        # Filter by job type
  GET    /api/v1/queue/jobs/{run_id}/children # Get child job stats (parent jobs)
  POST   /api/v1/queue/jobs/{run_id}/cancel   # Cancel job with cascade
  GET    /api/v1/queue/unified                # Unified queue statistics

Functions:
  GET    /api/v1/functions/                   # List all functions
  GET    /api/v1/functions/categories         # List categories
  GET    /api/v1/functions/{name}             # Get function details
  POST   /api/v1/functions/{name}/execute     # Execute function directly

Procedures:
  GET    /api/v1/procedures/                  # List procedures
  GET    /api/v1/procedures/{slug}            # Get procedure details
  POST   /api/v1/procedures/{slug}/run        # Execute procedure
  POST   /api/v1/procedures/{slug}/enable     # Enable procedure
  POST   /api/v1/procedures/{slug}/disable    # Disable procedure

Pipelines:
  GET    /api/v1/pipelines/                   # List pipelines
  GET    /api/v1/pipelines/{slug}             # Get pipeline details
  POST   /api/v1/pipelines/{slug}/run         # Execute pipeline
  GET    /api/v1/pipelines/{slug}/runs/{id}/items  # Get item states

Webhooks:
  POST   /api/v1/webhooks/procedures/{slug}   # Trigger procedure via webhook
  POST   /api/v1/webhooks/pipelines/{slug}    # Trigger pipeline via webhook

System:
  GET    /api/v1/system/health/comprehensive    # Full health check
```

---

## Scheduled Maintenance Tasks

Curatore uses a scheduled task system for background maintenance operations. Tasks are defined in the database (`ScheduledTask` model) and executed by Celery workers.

### Naming Convention

Task types follow the pattern `{domain}.{action}`:
- **domain**: The resource area being acted upon
- **action**: A verb or verb_modifier describing the operation

### Handler Reference

| Task Type | Handler | Description |
|-----------|---------|-------------|
| **Assets Domain** |||
| `assets.detect_orphans` | `handle_orphan_detection` | Find/fix orphaned assets: stuck pending, missing files, orphaned SharePoint docs |
| **Runs Domain** |||
| `runs.cleanup_stale` | `handle_stale_run_cleanup` | Reset runs stuck in pending/submitted/running; retry before failing |
| `runs.cleanup_expired` | `handle_cleanup_expired_runs` | Delete old completed/failed runs after retention period |
| **Retention Domain** |||
| `retention.enforce` | `handle_retention_enforcement` | Mark old temp artifacts as deleted per retention policy |
| **Health Domain** |||
| `health.report` | `handle_health_report` | Generate system health summary with metrics and warnings |
| **Search Domain** |||
| `search.reindex` | `handle_search_reindex` | Rebuild PostgreSQL full-text + semantic search index |
| **SharePoint Domain** |||
| `sharepoint.trigger_sync` | `handle_sharepoint_scheduled_sync` | Trigger syncs for configs with specified frequency |
| **SAM.gov Domain** |||
| `sam.trigger_pull` | `handle_sam_scheduled_pull` | Trigger pulls for searches with specified frequency |
| **Extraction Domain** |||
| `extraction.queue_orphans` | `handle_queue_pending_assets` | Safety net: queue extractions for orphaned pending assets |
| **Procedure Domain** |||
| `procedure.execute` | `handle_procedure_execute` | Execute a procedure from scheduled task |

### Legacy Aliases

For backwards compatibility, these old names map to canonical handlers:

| Legacy Name | Maps To |
|-------------|---------|
| `orphan.detect` | `assets.detect_orphans` |
| `stale_run.cleanup` | `runs.cleanup_stale` |
| `gc.cleanup` | `runs.cleanup_expired` |
| `sharepoint.scheduled_sync` | `sharepoint.trigger_sync` |
| `sam.scheduled_pull` | `sam.trigger_pull` |
| `extraction.queue_pending` | `extraction.queue_orphans` |

### Handler Details

#### `assets.detect_orphans`
Finds and fixes orphaned assets:
- Assets stuck in "pending" status (auto-retries extraction, up to 3 times)
- Assets marked "ready" but missing extraction results
- Assets with missing raw files in object storage
- Orphaned SharePoint assets (sync config deleted/archived)

**Config:**
```json
{"auto_fix": true}
```

#### `runs.cleanup_stale`
Resets or fails runs stuck in non-terminal states:
- `submitted` runs older than `stale_submitted_minutes` (default: 30)
- `running` runs older than `stale_running_hours` (default: 2)
- `pending` runs older than `stale_pending_hours` (default: 1)
- Retries up to `max_retries` (default: 3) before marking as failed

**Config:**
```json
{
  "stale_submitted_minutes": 30,
  "stale_running_hours": 2,
  "stale_pending_hours": 1,
  "max_retries": 3,
  "dry_run": false
}
```

#### `runs.cleanup_expired`
Deletes old completed/failed runs and their log events:
- Only deletes runs in terminal states (completed, failed, cancelled, timed_out)
- Respects `retention_days` config (default: 30)
- Processes up to `batch_size` runs per execution (default: 1000)

**Config:**
```json
{
  "retention_days": 30,
  "batch_size": 1000,
  "dry_run": false
}
```

#### `sharepoint.trigger_sync` / `sam.trigger_pull`
Trigger scheduled syncs/pulls for configs with matching frequency:
- Skips configs that already have a running sync/pull
- Creates new Run record and dispatches Celery task

**Config:**
```json
{"frequency": "hourly"}  // or "daily"
```

### Adding a New Maintenance Handler

1. Add handler function in `backend/app/services/maintenance_handlers.py`:
```python
async def handle_my_task(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Docstring describing the handler."""
    await _log_event(session, run.id, "INFO", "start", "Starting my task")
    # ... implementation ...
    return {"status": "completed", ...}
```

2. Register in `MAINTENANCE_HANDLERS` dict with canonical name:
```python
MAINTENANCE_HANDLERS = {
    # ... existing handlers ...
    "mydomain.myaction": handle_my_task,
}
```

3. Add default scheduled task in `backend/app/commands/seed.py`:
```python
{
    "name": "my_task",
    "display_name": "My Task",
    "description": "What this task does",
    "task_type": "mydomain.myaction",
    "scope_type": "global",
    "schedule_expression": "0 * * * *",  # Cron expression
    "enabled": True,
    "config": {},
},
```

4. Re-seed scheduled tasks:
```bash
docker exec curatore-backend python -m app.commands.seed --seed-scheduled-tasks
```

---

## Debugging

```bash
# Check services
docker ps

# View logs
docker-compose logs -f backend
docker-compose logs -f worker

# Check Celery tasks
docker exec -it curatore-worker celery -A app.celery_app inspect active

# Check Redis
docker exec -it curatore-redis redis-cli keys '*'

# Check PostgreSQL
docker exec -it curatore-postgres psql -U curatore -d curatore -c "\dt"

# Test extraction
curl -X POST http://localhost:8010/api/v1/extract -F "file=@test.pdf"
```

---

## Port Mappings

| Port | Service |
|------|---------|
| 3000 | Frontend |
| 5432 | PostgreSQL (with pgvector) |
| 8000 | Backend API |
| 8010 | Extraction Service |
| 8011 | Playwright Service |
| 6379 | Redis |
| 9000 | MinIO S3 API |
| 9001 | MinIO Console |

---

## Testing

```bash
# All tests
./scripts/run_all_tests.sh

# Backend only
pytest backend/tests -v

# Extraction service
pytest extraction-service/tests -v

# Frontend
cd frontend && npm test
```

---

## Common Tasks

### Re-extract a document
```bash
curl -X POST http://localhost:8000/api/v1/assets/{asset_id}/reextract \
  -H "Authorization: Bearer $TOKEN"
```

### Trigger search reindex
```bash
curl -X POST http://localhost:8000/api/v1/search/reindex \
  -H "Authorization: Bearer $TOKEN"
```

### Start a web crawl
```bash
curl -X POST http://localhost:8000/api/v1/scrape/collections/{id}/crawl \
  -H "Authorization: Bearer $TOKEN"
```

### Pull SAM.gov opportunities
```bash
curl -X POST http://localhost:8000/api/v1/sam/searches/{id}/pull \
  -H "Authorization: Bearer $TOKEN"
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [`docs/DOCUMENT_PROCESSING.md`](docs/DOCUMENT_PROCESSING.md) | Detailed document processing pipeline with diagrams |
| [`config.yml.example`](config.yml.example) | Configuration reference |
| [`docker-compose.yml`](docker-compose.yml) | Service architecture |
