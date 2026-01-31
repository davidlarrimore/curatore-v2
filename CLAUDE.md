# CLAUDE.md

Development guidance for Claude Code working with Curatore v2.

## Project Overview

Curatore v2 is a document processing and curation platform that converts documents to Markdown, provides full-text search, and supports LLM-powered analysis.

### Tech Stack
- **Backend**: FastAPI (Python 3.12+), Celery workers, SQLAlchemy
- **Frontend**: Next.js 15.5, TypeScript, React 19, Tailwind CSS
- **Services**: Redis, MinIO/S3, OpenSearch (optional), Playwright, Extraction Service
- **Database**: PostgreSQL 16 (required)

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
| `extraction_queue_service.py` | Extraction queue throttling and management |
| `queue_registry.py` | Queue type definitions and capabilities |
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
| `queue_admin.py` | Job Manager: queue registry, active jobs, cancel/boost |
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

### New Queue Type (for background job processing)

The Queue Registry (`backend/app/services/queue_registry.py`) defines all job queue types programmatically. Each queue type has its own Celery queue for isolation and configurable capabilities.

**Existing Queue Types:**
| Queue | Run Type | Celery Queue | Capabilities |
|-------|----------|--------------|--------------|
| Extraction | `extraction` | `extraction` | cancel, boost, retry |
| SAM.gov | `sam_pull` | `sam` | - |
| Web Scrape | `scrape` | `scrape` | - |
| SharePoint | `sharepoint_sync` | `sharepoint` | cancel |
| Maintenance | `system_maintenance` | `maintenance` | - |

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
            can_boost=False,                     # No priority boosting
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
celery -A app.celery_app worker -Q processing_priority,extraction,sam,scrape,sharepoint,google_drive,maintenance
```

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
                                    │ DeletionJobsProvider│
                                    │ polls Run status    │
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
1. Add `DeletionJobsProvider` to app layout (already done)
2. Use `useDeletionJobs()` hook in components:
```tsx
const { addJob, isDeleting } = useDeletionJobs()

const handleDelete = async () => {
  const { run_id } = await api.deleteConfig(id)
  addJob({ runId: run_id, configId: id, configName: name, configType: 'sharepoint' })
  router.push('/list')  // Redirect immediately
}
```

3. Show "Deleting..." state in list views:
```tsx
{config.status === 'deleting' || isDeleting(config.id) ? (
  <Badge>Deleting...</Badge>
) : ...}
```

**Key Files:**
- `backend/app/tasks.py` - `async_delete_sync_config_task`
- `frontend/lib/deletion-jobs-context.tsx` - Global job tracking
- `frontend/components/ui/ConfirmDeleteDialog.tsx` - Reusable dialog

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
OPENSEARCH_ENABLED=false
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
  POST   /api/v1/queue/jobs/{run_id}/cancel   # Cancel a job
  GET    /api/v1/queue/unified                # Unified queue statistics

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
| 5432 | PostgreSQL |
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
