# CLAUDE.md

Development guidance for Claude Code working with Curatore v2.

## Project Overview

Curatore v2 is a document processing and curation platform that converts documents to Markdown, provides full-text search, and supports LLM-powered analysis.

### Tech Stack
- **Backend**: FastAPI (Python 3.12+), Celery workers, SQLAlchemy
- **Frontend**: Next.js 15.5, TypeScript, React 19, Tailwind CSS
- **Services**: Redis, MinIO/S3, OpenSearch (optional), Playwright, Extraction Service
- **Database**: SQLite (dev) / PostgreSQL (prod)

### Architecture Principles
1. **Extraction is infrastructure** - Automatic on upload, not per-workflow
2. **Assets are first-class** - Documents tracked with version history and provenance
3. **Run-based execution** - All processing tracked via Run records with structured logs
4. **Database is source of truth** - Object store contains only bytes

### Key Data Models
| Model | Purpose |
|-------|---------|
| `Asset` | Document with provenance and version history |
| `AssetVersion` | Individual versions of an asset |
| `ExtractionResult` | Extracted markdown linked to asset version |
| `Run` | Universal execution tracking (extraction, crawl, summarization) |
| `RunLogEvent` | Structured logging for runs |
| `ScrapeCollection` | Web scraping project with seed URLs |
| `SamSearch/SamSolicitation` | SAM.gov federal opportunity tracking |
| `ScheduledTask` | Database-backed scheduled maintenance |

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
│   ├── database/models.py  # SQLAlchemy models
│   └── tasks.py            # Celery tasks
├── alembic/                # Database migrations

frontend/
├── app/                    # Next.js App Router pages
├── components/             # React components
└── lib/api.ts              # API client

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
| `extraction_orchestrator.py` | Extraction coordination |
| `opensearch_service.py` | Full-text search with facets |
| `minio_service.py` | Object storage operations |
| `sam_service.py` | SAM.gov API integration |
| `scrape_service.py` | Web scraping collections |
| `scheduled_task_service.py` | Scheduled maintenance |
| `auth_service.py` | JWT/API key authentication |
| `connection_service.py` | Runtime service connections |

### Key Routers (`backend/app/api/v1/routers/`)

| Router | Endpoints |
|--------|-----------|
| `assets.py` | Asset CRUD, versions, re-extraction |
| `runs.py` | Run status, logs, retry |
| `search.py` | Full-text search with facets |
| `sam.py` | SAM.gov searches, solicitations, notices |
| `scrape.py` | Web scraping collections |
| `storage.py` | File upload/download |
| `scheduled_tasks.py` | Maintenance task admin |

---

## Data Flow

```
Upload → Asset Created → Automatic Extraction → ExtractionResult → OpenSearch Index
                              ↓
                         Run (tracks execution)
                              ↓
                         RunLogEvent (structured logs)
```

### Processing Workflow
1. **Upload**: `POST /api/v1/storage/upload/proxy` creates Asset, triggers extraction
2. **Extraction**: Celery task converts to Markdown, stores in MinIO
3. **Indexing**: Asset indexed in OpenSearch (if enabled)
4. **Access**: `GET /api/v1/assets/{id}` returns asset with extraction_result

---

## Object Storage Structure

```
curatore-uploads/{org_id}/
├── uploads/{asset_uuid}/{filename}      # File uploads
├── scrape/{collection}/pages/           # Scraped web pages
├── scrape/{collection}/documents/       # Downloaded documents
├── sharepoint/{site}/{path}/            # SharePoint files
└── sam/solicitations/{number}/          # SAM.gov attachments

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

---

## Configuration

### Key Environment Variables

```bash
# Required
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# Optional
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENSEARCH_ENABLED=false
SAM_API_KEY=your_key
ENABLE_AUTH=false
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

System:
  GET    /api/v1/system/health/comprehensive    # Full health check
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

# Test extraction
curl -X POST http://localhost:8010/api/v1/extract -F "file=@test.pdf"
```

---

## Port Mappings

| Port | Service |
|------|---------|
| 3000 | Frontend |
| 8000 | Backend API |
| 8010 | Extraction Service |
| 8011 | Playwright Service |
| 6379 | Redis |
| 9000 | MinIO S3 API |
| 9001 | MinIO Console |
| 9200 | OpenSearch |

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
