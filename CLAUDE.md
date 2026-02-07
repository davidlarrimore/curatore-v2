# CLAUDE.md

Development guidance for Claude Code working with Curatore v2.

## Quick Navigation

**Getting Started**: [Quick Start](#quick-start) | [Project Structure](#project-structure) | [Dev Commands](#development-commands)

**Core Systems**: [Architecture](#architecture-principles) | [Data Models](#key-data-models) | [Search & Indexing](docs/SEARCH_INDEXING.md) | [Queue System](docs/QUEUE_SYSTEM.md)

**Integrations**: [SAM.gov](docs/SAM_INTEGRATION.md) | [Salesforce](docs/SALESFORCE_INTEGRATION.md) | [SharePoint](docs/SHAREPOINT_INTEGRATION.md) | [Forecasts](docs/FORECAST_INTEGRATION.md) | [Web Scraping](docs/DATA_CONNECTIONS.md#web-scraping)

**Workflows**: [Functions & Procedures](docs/FUNCTIONS_PROCEDURES.md) | [Document Processing](docs/DOCUMENT_PROCESSING.md)

**Reference**: [API Docs](docs/API_DOCUMENTATION.md) | [Configuration](docs/CONFIGURATION.md) | [Maintenance Tasks](docs/MAINTENANCE_TASKS.md)

---

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
| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |
| PostgreSQL | localhost:5432 (curatore/curatore_dev_password) |

### Port Mappings
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

# All tests
./scripts/run_all_tests.sh
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/v1/routers/     # API endpoints
│   ├── services/           # Business logic
│   ├── database/models.py  # SQLAlchemy models
│   ├── functions/          # Function library (llm, search, output, etc.)
│   ├── procedures/         # Procedure executor and YAML definitions
│   ├── pipelines/          # Pipeline executor and YAML definitions
│   └── tasks.py            # Celery tasks
├── alembic/                # Database migrations

frontend/
├── app/                    # Next.js App Router pages
│   ├── admin/              # Functions, procedures, pipelines, queue
│   ├── sam/                # SAM.gov interface
│   ├── salesforce/         # Salesforce CRM (accounts, contacts, opportunities)
│   ├── forecasts/          # Acquisition forecasts
│   ├── sharepoint-sync/    # SharePoint sync
│   └── scrape/             # Web scraping
├── components/             # React components
└── lib/
    ├── api.ts                    # API client
    ├── unified-jobs-context.tsx  # WebSocket-based job tracking
    └── job-type-config.ts        # Job type configuration

extraction-service/         # Document conversion microservice
playwright-service/         # Browser rendering microservice
```

---

## Key Data Models

| Model | Purpose |
|-------|---------|
| `Asset` | Document with provenance, version history, and pipeline status |
| `AssetVersion` | Individual versions of an asset |
| `ExtractionResult` | Extracted markdown with triage metadata |
| `Run` | Universal execution tracking (extraction, crawl, sync) |
| `RunGroup` | Parent-child job tracking for group completion |
| `RunLogEvent` | Structured logging for runs |
| `ContentItem` | Universal content wrapper for functions/procedures (in-memory) |

### Integration Models
| Model | Purpose |
|-------|---------|
| `SamSearch` | SAM.gov saved search configuration |
| `SamSolicitation` | Groups SAM.gov notices with same solicitation number |
| `SamNotice` | Individual SAM.gov notice |
| `ForecastSync` | Forecast sync configuration |
| `SharePointSyncConfig` | SharePoint folder sync configuration |
| `ScrapeCollection` | Web scraping project with seed URLs |
| `SalesforceConnection` | Salesforce org connection credentials |

### Workflow Models
| Model | Purpose |
|-------|---------|
| `Procedure` | Reusable workflow definitions (scheduled, event-driven) |
| `Pipeline` | Multi-stage document processing workflows |
| `ScheduledTask` | Database-backed scheduled maintenance |

---

## Core Services

### Backend Services (`backend/app/services/`)

| Service | Purpose |
|---------|---------|
| `asset_service.py` | Asset CRUD and version management |
| `run_service.py` | Run execution tracking |
| `run_group_service.py` | Parent-child job tracking for group completion |
| `event_service.py` | Event emission for triggering procedures/pipelines |
| `extraction_orchestrator.py` | Extraction coordination with triage |
| `extraction_queue_service.py` | Extraction queue throttling and management |
| `queue_registry.py` | Queue type definitions and capabilities |
| `pg_search_service.py` | Hybrid full-text + semantic search |
| `pg_index_service.py` | Document chunking, embedding, and indexing |
| `metadata_builders.py` | Namespaced metadata builder registry for search indexing |
| `minio_service.py` | Object storage operations |
| `auth_service.py` | JWT/API key authentication |

### Integration Services
| Service | Purpose |
|---------|---------|
| `sam_pull_service.py` | SAM.gov API integration |
| `salesforce_service.py` | Salesforce CRM operations |
| `forecast_sync_service.py` | Forecast sync management |
| `sharepoint_sync_service.py` | SharePoint sync |
| `scrape_service.py` | Web scraping |

### Key Routers (`backend/app/api/v1/routers/`)

| Router | Endpoints |
|--------|-----------|
| `assets.py` | Asset CRUD, versions, re-extraction |
| `runs.py` | Run status, logs, retry |
| `queue_admin.py` | Job Manager: registry, active jobs, cancel |
| `search.py` | Full-text + semantic search |
| `sam.py` | SAM.gov searches, solicitations, notices |
| `salesforce.py` | Salesforce accounts, contacts, opportunities |
| `forecasts.py` | Forecast syncs and unified view |
| `sharepoint_sync.py` | SharePoint sync configuration |
| `scrape.py` | Web scraping collections |
| `functions.py` | Function browser and execution |
| `procedures.py` | Procedure CRUD and execution |

---

## Queue Architecture

All background jobs are managed through the Queue Registry system. See [Queue System](docs/QUEUE_SYSTEM.md) for details.

**Queue Types:**
| Queue | Run Type | Purpose |
|-------|----------|---------|
| Extraction | `extraction` | Document processing |
| SAM.gov | `sam_pull` | SAM.gov data sync |
| Forecasts | `forecast_pull` | Acquisition forecast sync |
| Web Scrape | `scrape` | Web crawling |
| SharePoint | `sharepoint_sync` | SharePoint sync |
| Maintenance | `system_maintenance` | Background tasks |
| Procedure | `procedure` | Workflow execution |
| Pipeline | `pipeline` | Pipeline execution |

---

## Search Architecture

PostgreSQL with pgvector for hybrid full-text + semantic search:

- **Full-text search**: PostgreSQL tsvector + GIN indexes
- **Semantic search**: pgvector embeddings (1536-dim via OpenAI)
- **Hybrid mode**: Configurable keyword/semantic weighting
- **Chunking**: ~1500 char chunks with 200 char overlap
- **Namespaced metadata**: `search_chunks.metadata` uses nested JSONB namespaces (`source`, `sharepoint`, `sam`, `salesforce`, `forecast`, `custom`) built via `MetadataBuilder` registry
- **AssetMetadata bridge**: Canonical LLM-generated metadata is propagated to the `custom` namespace for searchability
- **Metadata filtering**: Generic `metadata_filters` parameter on search uses JSONB `@>` containment on the GIN index
- **Schema discovery**: `GET /api/v1/search/metadata-schema` returns available namespaces, fields, sample values, and doc counts (cached 5 min, invalidated on index operations)

Indexed content types: assets, SAM solicitations/notices, forecasts, scraped pages.

---

## Data Flow

```
Upload → Asset Created → Triage → Extraction → Indexing → Search Ready
                           ↓          ↓
                   Select Engine   Run (tracks execution)
                                       ↓
                                  RunLogEvent (logs)
```

1. **Upload**: `POST /api/v1/storage/upload/proxy` creates Asset
2. **Triage**: Analyzes document to select optimal engine (< 100ms)
3. **Extraction**: Routes to fast_pdf, extraction-service, or docling
4. **Indexing**: Chunks content, generates embeddings, indexes to search
5. **Access**: `GET /api/v1/assets/{id}` returns asset with extraction

---

## Object Storage Structure

```
curatore-uploads/{org_id}/
├── uploads/{asset_uuid}/{filename}      # File uploads
├── scrape/{collection}/pages/           # Scraped web pages
├── sharepoint/{site}/{path}/            # SharePoint files
└── sam/{agency}/{bureau}/               # SAM.gov attachments

curatore-processed/{org_id}/             # Extracted markdown
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
3. Create Run record for tracking

### New Queue Type
See [Queue System - Adding New Queue Types](docs/QUEUE_SYSTEM.md#adding-new-queue-types)

### New Data Integration
See [Data Connections Guide](docs/DATA_CONNECTIONS.md)

---

## Frontend Patterns

### Design System
- **Colors**: Indigo/purple primary, emerald success, red error, amber warning
- **Icons**: Lucide React (`lucide-react`)
- **Dark Mode**: All components use `dark:` prefix

### Real-Time Job Tracking
WebSocket-based with automatic polling fallback:

```tsx
import { useActiveJobs } from '@/lib/context-shims'

function MyPage() {
  const { addJob, getJobsForResource, isResourceBusy } = useActiveJobs()

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
}
```

**Key Files:**
- `frontend/lib/unified-jobs-context.tsx` - Job tracking
- `frontend/lib/context-shims.ts` - Backward-compatible hooks
- `frontend/components/ui/RunningJobBanner.tsx` - Job status banner

---

## API Quick Reference

```
Assets:        GET/POST /api/v1/assets, POST /assets/{id}/reextract
Runs:          GET /api/v1/runs, GET /runs/{id}/logs
Search:        POST /api/v1/search, GET /search/metadata-schema
Storage:       POST /api/v1/storage/upload/proxy
Queue:         GET /api/v1/queue/jobs, POST /queue/jobs/{id}/cancel
SAM.gov:       GET /api/v1/sam/searches, /solicitations, /notices
Salesforce:    GET /api/v1/salesforce/accounts, /contacts, /opportunities
Forecasts:     GET /api/v1/forecasts/syncs, GET /forecasts
Functions:     GET /api/v1/functions, POST /functions/{name}/execute
Procedures:    GET /api/v1/procedures, POST /procedures/{slug}/run
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
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [Search & Indexing](docs/SEARCH_INDEXING.md) | Hybrid search, pgvector, chunking, embeddings, reindexing |
| [Queue System](docs/QUEUE_SYSTEM.md) | Queue architecture, job groups, cancellation |
| [SAM.gov Integration](docs/SAM_INTEGRATION.md) | SAM.gov data model and API |
| [Salesforce Integration](docs/SALESFORCE_INTEGRATION.md) | Salesforce CRM integration |
| [SharePoint Integration](docs/SHAREPOINT_INTEGRATION.md) | SharePoint folder sync |
| [Forecast Integration](docs/FORECAST_INTEGRATION.md) | Acquisition forecast sources |
| [Functions & Procedures](docs/FUNCTIONS_PROCEDURES.md) | Workflow automation |
| [Data Connections](docs/DATA_CONNECTIONS.md) | Adding new integrations |
| [Document Processing](docs/DOCUMENT_PROCESSING.md) | Extraction pipeline |
| [Maintenance Tasks](docs/MAINTENANCE_TASKS.md) | Scheduled background tasks |
| [Configuration](docs/CONFIGURATION.md) | Environment and YAML config |
| [API Documentation](docs/API_DOCUMENTATION.md) | Complete API reference |
