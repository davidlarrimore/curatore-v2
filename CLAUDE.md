# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Curatore v2 is a RAG-ready document processing and optimization platform. It converts documents (PDF, DOCX, PPTX, TXT, Images) to Markdown, evaluates quality with an LLM, and optionally optimizes structure for vector databases. The application consists of:

- **Backend**: FastAPI (Python 3.12+) with async Celery workers
- **Frontend**: Next.js 15.5 (TypeScript, React 19) with Tailwind CSS
- **Extraction Service**: Separate microservice for document conversion
- **Queue System**: Redis + Celery for async job processing
- **Optional Docling**: External document converter for rich PDFs/Office docs
- **Optional Object Storage**: S3-compatible storage (MinIO/AWS S3) with integrated MinIO SDK

## 🚧 ONGOING: Architecture Refactor (Multi-Session Project)

**Status**: Phase 0 (Stabilization & Baseline Observability) - IN PROGRESS
**Started**: 2026-01-28

### Quick Start for Each Session

1. **Read progress tracker first**: `/ARCHITECTURE_PROGRESS.md` (~300 lines)
2. **Only reference full requirements when needed**: `/UPDATED_DATA_ARCHITECTURE.md` (~1400 lines)
3. **Update progress tracker** as you complete tasks

### Project Summary

Curatore is evolving from a document processing tool into a curation-first platform that:
- Separates import, canonicalization, processing, and output sync
- Treats extraction as automatic infrastructure (not per-workflow config)
- Prioritizes experimentation speed over premature automation
- Maintains DB as source of truth with strict object store layout

### Core Architectural Principles
1. **Extraction is infrastructure** - Automatic, opinionated, consistent
2. **Experimentation precedes automation** - Test/compare before pipelines
3. **Artifacts are first-class** - Every output is addressable and reusable
4. **Separation of concerns** - Import ≠ Processing ≠ Output Sync
5. **UI explains outcomes** - Users see assets/results, not jobs/queues

### Implementation Phases (0-7)
- **Phase 0** (Current): Stabilization - Make behavior explicit and traceable
- **Phase 1**: Asset versioning and Document Detail View
- **Phase 2**: Bulk upload updates and collection health
- **Phase 3**: Flexible metadata and experimentation core
- **Phase 4**: Web scraping as durable data source
- **Phase 5**: System maintenance and scheduling
- **Phase 6**: Optional integrations (vector DB, webhooks)
- **Phase 7**: SAM.gov native domain integration

### Token Efficiency Strategy
- Each session reads progress tracker (~300 lines) instead of full requirements (~1400 lines)
- Reference specific sections of UPDATED_DATA_ARCHITECTURE.md only when needed
- Saves ~15,000 tokens per session startup

---

## Development Commands

### Starting the Application

```bash
# Start all services (backend, worker, frontend, redis, extraction)
./scripts/dev-up.sh

# Or using Make (respects ENABLE_DOCLING_SERVICE env var)
make up

# View logs for all services
./scripts/dev-logs.sh

# View logs for specific service
./scripts/dev-logs.sh backend
./scripts/dev-logs.sh worker
```

### Backend Development

```bash
# Run backend tests (from project root)
pytest backend/tests -v

# Run backend with hot-reload (manual, outside Docker)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run single test file
pytest backend/tests/test_document_service.py -v
```

### Frontend Development

```bash
# Run frontend dev server (manual, outside Docker)
cd frontend
npm install
npm run dev

# Type checking
npm run type-check

# Linting
npm run lint
```

### Worker Development

```bash
# View worker logs in real-time
./scripts/tail_worker.sh

# Worker runs with watchmedo for auto-restart on code changes
# No manual restart needed during development
```

### Testing

```bash
# Run all tests across services (backend, extraction, frontend)
./scripts/run_all_tests.sh

# Quick backend tests only
pytest backend/tests

# Run extraction service tests
pytest extraction-service/tests -v

# API smoke tests
./scripts/api_smoke_test.sh
```

### Queue & Job Management

```bash
# Check queue health (Redis, Celery, workers)
./scripts/queue_health.sh

# Enqueue document and poll for completion
./scripts/enqueue_and_poll.sh <document_id>
```

### SharePoint Operations

```bash
# Test SharePoint connectivity and authentication
python scripts/sharepoint/sharepoint_connect.py

# List files in SharePoint folder (inventory)
python scripts/sharepoint/sharepoint_inventory.py

# Download files from SharePoint to batch directory
python scripts/sharepoint/sharepoint_download.py

# End-to-end: inventory, download, and process
python scripts/sharepoint/sharepoint_process.py

# Note: All scripts require MS_TENANT_ID, MS_CLIENT_ID, and MS_CLIENT_SECRET
# in .env file or environment variables
```

### Cleanup

```bash
# Stop all services
./scripts/dev-down.sh

# Clean up containers, volumes, and images
./scripts/clean.sh

# Nuclear option: remove everything including networks
./scripts/nuke.sh

# Storage cleanup (for breaking changes to storage layer)
# Automatically recreates buckets and organization folders after cleanup
# See docs/STORAGE_CLEANUP.md for full documentation
./scripts/cleanup_storage.sh --dry-run  # Preview what would be deleted
./scripts/cleanup_storage.sh            # Interactive cleanup + recreation
./scripts/cleanup_storage.sh --force    # Force cleanup + recreation
```

## Architecture Overview

### Service Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend    │────▶│    Redis    │
│  (Next.js)  │     │  (FastAPI)   │     │  (Broker)   │
└─────────────┘     └──────────────┘     └─────────────┘
                            │                     │
                            │                     ▼
                            │             ┌──────────────┐
                            │             │    Worker    │
                            │             │   (Celery)   │
                            │             └──────────────┘
                            │                     │
                            ▼                     ▼
        ┌──────────────┬──────────────┐  ┌──────────────┐
        │  Extraction  │  Playwright  │  │   Storage    │
        │   Service    │   Service    │  │   (MinIO)    │
        └──────────────┴──────────────┘  └──────────────┘
                │               │
                ▼               │
        ┌──────────────┐        │
        │   Docling    │        │
        │  (Optional)  │        │
        └──────────────┘        │
                                │
        Content-Type Routing: ──┘
        - HTML → Playwright (inline extraction)
        - PDF/DOCX → Extraction Service/Docling
```

### Backend Service Layer

The backend follows a service-oriented architecture with clear separation of concerns:

- **`document_service.py`**: Core document processing pipeline
  - Multi-format conversion using selected extraction engines
  - OCR integration for image-based content extraction
  - Delegates to extraction service or Docling based on per-job selection
  - Quality assessment and scoring algorithms
  - File management with UUID-based organization

- **`llm_service.py`**: LLM integration and evaluation
  - Flexible endpoint configuration (OpenAI, Ollama, OpenWebUI, LM Studio)
  - Multi-criteria document evaluation with detailed scoring
  - Vector optimization prompt engineering
  - Connection monitoring and error handling

- **`storage_service.py`**: In-memory storage management
  - Processing result caching with efficient retrieval
  - Batch operation state management
  - CRUD operations for individual and batch results
  - Automatic cross-referencing between batch and individual results

- **`zip_service.py`**: Archive creation and export
  - Individual document archives with processing summaries
  - Combined exports with merged documents
  - RAG-ready filtering with quality threshold application
  - Temporary file management with automatic cleanup

- **`job_service.py`**: Redis-backed job tracking
  - Per-document active job locks (prevents concurrent processing)
  - Job status persistence and indexing
  - Job logs and metadata management

- **`extraction_client.py`**: HTTP client for extraction service
  - Handles communication with extraction-service or Docling

- **`sharepoint_service.py`**: Microsoft SharePoint integration
  - Connects to SharePoint via Microsoft Graph API
  - Lists folder contents with metadata (inventory)
  - Downloads files to batch directory for processing
  - Supports recursive traversal and folder structure preservation
  - Uses Azure AD app-only authentication (client credentials flow)

- **`auth_service.py`**: Authentication and authorization
  - JWT token generation (access + refresh tokens)
  - API key generation and validation with bcrypt hashing
  - Password hashing and verification
  - Token refresh and validation logic

- **`database_service.py`**: Database session management
  - Async SQLAlchemy session handling
  - Supports SQLite (development) and PostgreSQL (production)
  - Connection pooling and health checks
  - Singleton pattern for global session management

- **`email_service.py`**: Email delivery system
  - Multiple backends: console (dev), SMTP, SendGrid, AWS SES
  - Email verification and password reset workflows
  - Template-based email generation
  - Configurable retry logic and error handling

- **`verification_service.py`**: Email verification management
  - Token generation and validation for email verification
  - Grace period enforcement before requiring verification
  - Integration with email service for delivery

- **`password_reset_service.py`**: Password reset workflows
  - Secure token generation for password reset links
  - Token expiration and validation
  - Integration with email service

- **`connection_service.py`**: Runtime-configurable connections
  - Store and manage external service connections (SharePoint, LLM, etc.)
  - Per-organization connection isolation
  - Automatic connection health testing
  - Secure credential storage

- **`scheduled_task_service.py`**: Database-backed scheduled task management
  - CRUD operations for ScheduledTask model
  - Enable/disable tasks at runtime
  - Manual trigger with Run tracking
  - Due task detection and execution coordination
  - Maintenance statistics aggregation

- **`lock_service.py`**: Redis-based distributed locking
  - Acquire/release locks for task idempotency
  - Lock extension for long-running operations
  - Atomic check-and-delete via Lua scripts
  - Prevents duplicate scheduled task execution

- **`maintenance_handlers.py`**: Scheduled maintenance task handlers
  - Job cleanup handler (expired jobs and data)
  - Orphan detection handler (storage cleanup)
  - Retention enforcement handler (policy compliance)
  - Health report handler (system status summary)
  - Extensible handler registry pattern

### API Structure

All API endpoints are versioned under `/api/v1/`:

```
backend/app/
├── api/
│   └── v1/
│       ├── routers/
│       │   ├── documents.py       # Document upload, process, download
│       │   ├── jobs.py            # Job status, polling
│       │   ├── sharepoint.py      # SharePoint inventory, download
│       │   ├── system.py          # Health, config, queue info
│       │   ├── auth.py            # Authentication (login, register, refresh)
│       │   ├── users.py           # User management
│       │   ├── organizations.py   # Organization/tenant management
│       │   ├── api_keys.py        # API key management
│       │   ├── connections.py     # Runtime connection management
│       │   └── scheduled_tasks.py # Scheduled task management (admin)
│       └── models.py              # V1-specific Pydantic models
├── models.py                      # Shared domain models
├── database/
│   ├── models.py                  # SQLAlchemy ORM models
│   └── base.py                    # SQLAlchemy base and metadata
├── commands/
│   └── seed.py                    # Database seeding command
└── services/                      # Business logic layer
```

**Important**: Always use `/api/v1/` paths. The legacy `/api/` alias exists for backwards compatibility but returns deprecation headers.

### Async Processing with Celery

Documents are processed asynchronously to avoid blocking the API:

1. **Upload**: `POST /api/v1/documents/upload` → returns `document_id`
2. **Enqueue**: `POST /api/v1/documents/{document_id}/process` → returns `job_id`
3. **Poll**: `GET /api/v1/jobs/{job_id}` → returns status (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`)
4. **Result**: `GET /api/v1/documents/{document_id}/result` → returns processing result

**Job Locks**: Only one job can process a document at a time. Attempting to enqueue while another job is active returns `409 Conflict` with the active job ID.

**Key Files**:
- `backend/app/celery_app.py`: Celery application setup
- `backend/app/tasks.py`: Task definitions (e.g., `process_document_task`)
- `backend/app/services/job_service.py`: Redis-backed job tracking

### Celery Beat & Scheduled Tasks

Curatore uses Celery Beat for periodic task scheduling. The system supports both hardcoded beat schedules and database-backed scheduled tasks for admin control.

#### Beat Service Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Celery     │────▶│    Redis     │────▶│   Celery    │
│   Beat      │     │   (Broker)   │     │   Worker    │
└─────────────┘     └──────────────┘     └─────────────┘
      │                                         │
      │ (every minute)                          │
      ▼                                         ▼
┌─────────────┐                         ┌──────────────┐
│ check_      │                         │  Execute     │
│ scheduled_  │────────────────────────▶│  Scheduled   │
│ tasks       │   (enqueue due tasks)   │  Task        │
└─────────────┘                         └──────────────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │ Maintenance  │
                                        │  Handlers    │
                                        └──────────────┘
```

#### Docker Service

The beat service runs separately from workers in Docker:

```yaml
# docker-compose.yml
beat:
  build:
    context: ./backend
  container_name: curatore-beat
  command: celery -A app.celery_app beat -l info
  environment:
    - SCHEDULED_TASK_CHECK_ENABLED=${SCHEDULED_TASK_CHECK_ENABLED:-true}
    - SCHEDULED_TASK_CHECK_INTERVAL=${SCHEDULED_TASK_CHECK_INTERVAL:-60}
    # ... same env vars as worker
  depends_on:
    - redis
    - backend
```

#### Hardcoded Beat Schedules

Defined in `backend/app/celery_app.py`:

```python
celery_app.conf.beat_schedule = {
    # Check for due scheduled tasks every minute
    "check-scheduled-tasks": {
        "task": "app.tasks.check_scheduled_tasks",
        "schedule": crontab(minute="*"),  # Every minute
    },
    # Cleanup expired temp files
    "cleanup-expired-files": {
        "task": "app.tasks.cleanup_expired_files",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
    },
    # Cleanup expired jobs
    "cleanup-expired-jobs": {
        "task": "app.tasks.cleanup_expired_jobs",
        "schedule": crontab(hour=4, minute=0),  # Daily at 4 AM
    },
}
```

**To add a new hardcoded beat:**

1. Create the task in `backend/app/tasks.py`:
   ```python
   @celery_app.task(name="app.tasks.my_new_task")
   def my_new_task():
       """My periodic task."""
       logger.info("Running my_new_task")
       # Task logic here
   ```

2. Add to beat schedule in `backend/app/celery_app.py`:
   ```python
   celery_app.conf.beat_schedule["my-new-task"] = {
       "task": "app.tasks.my_new_task",
       "schedule": crontab(hour=5, minute=30),  # Daily at 5:30 AM
   }
   ```

3. Restart the beat service: `docker-compose restart beat`

#### Database-Backed Scheduled Tasks

For admin-controllable scheduled tasks, use the `ScheduledTask` model. These tasks can be enabled/disabled and triggered manually via the admin UI.

**ScheduledTask Model:**
```python
class ScheduledTask(Base):
    id: UUID
    organization_id: Optional[UUID]  # Null for global tasks
    name: str                        # Unique identifier (e.g., "gc.cleanup")
    display_name: str                # UI display name
    description: Optional[str]
    task_type: str                   # Handler type (gc.cleanup, orphan.detect, etc.)
    scope_type: str                  # "global" or "organization"
    schedule_expression: str         # Cron format (e.g., "0 3 * * *")
    enabled: bool                    # Enable/disable toggle
    config: Dict[str, Any]           # Task-specific configuration
    last_run_id: Optional[UUID]      # Link to last Run record
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
```

**Default Scheduled Tasks** (seeded automatically):
| Task | Schedule | Description |
|------|----------|-------------|
| `gc.cleanup` | Daily 3 AM | Clean up expired jobs and orphaned data |
| `orphan.detect` | Weekly Sunday 4 AM | Detect orphaned objects in storage |
| `retention.enforce` | Daily 5 AM | Enforce data retention policies |
| `health.report` | Daily 6 AM | Generate system health summary |

**To add a new database-backed scheduled task:**

1. Create a handler in `backend/app/services/maintenance_handlers.py`:
   ```python
   async def handle_my_task(
       session: AsyncSession,
       run: Run,
       task: ScheduledTask,
       log_event: Callable,
   ) -> Dict[str, Any]:
       """My custom maintenance task."""
       await log_event("info", "Starting my task...")

       # Task logic here
       items_processed = 0

       await log_event("info", f"Processed {items_processed} items")
       return {"items_processed": items_processed}
   ```

2. Register the handler in the same file:
   ```python
   MAINTENANCE_HANDLERS: Dict[str, MaintenanceHandler] = {
       "gc.cleanup": handle_job_cleanup,
       "orphan.detect": handle_orphan_detection,
       "retention.enforce": handle_retention_enforcement,
       "health.report": handle_health_report,
       "my.task": handle_my_task,  # Add your handler
   }
   ```

3. Seed the task in `backend/app/commands/seed.py` (add to `DEFAULT_SCHEDULED_TASKS`):
   ```python
   {
       "name": "my.task",
       "display_name": "My Custom Task",
       "description": "Description of what this task does",
       "task_type": "my.task",
       "scope_type": "global",
       "schedule_expression": "0 7 * * *",  # Daily at 7 AM
       "enabled": True,
       "config": {},
   },
   ```

4. Run the seed command: `python -m app.commands.seed --seed-scheduled-tasks`

#### Scheduled Task Execution Flow

1. **Beat checks every minute**: `check_scheduled_tasks` finds due tasks
2. **Lock acquired**: Redis-based distributed lock prevents duplicate execution
3. **Run created**: A `Run` record tracks the execution (`run_type="system_maintenance"`)
4. **Handler executed**: Appropriate handler from `MAINTENANCE_HANDLERS` is called
5. **Results logged**: Handler logs events via `RunLogEvent`
6. **Task updated**: `last_run_at` and `next_run_at` are updated

#### Admin API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /scheduled-tasks` | List all scheduled tasks |
| `GET /scheduled-tasks/{id}` | Get task details |
| `POST /scheduled-tasks/{id}/enable` | Enable a task |
| `POST /scheduled-tasks/{id}/disable` | Disable a task |
| `POST /scheduled-tasks/{id}/trigger` | Trigger task immediately |
| `GET /scheduled-tasks/{id}/runs` | Get task run history |
| `GET /scheduled-tasks/stats` | Get maintenance statistics |

#### Key Files

| File | Purpose |
|------|---------|
| `backend/app/celery_app.py` | Celery app with beat schedule |
| `backend/app/tasks.py` | Task definitions including `check_scheduled_tasks` |
| `backend/app/database/models.py` | `ScheduledTask` model |
| `backend/app/services/scheduled_task_service.py` | CRUD and execution logic |
| `backend/app/services/maintenance_handlers.py` | Handler implementations |
| `backend/app/services/lock_service.py` | Distributed locking |
| `backend/app/api/v1/routers/scheduled_tasks.py` | Admin API endpoints |
| `frontend/components/admin/SystemMaintenanceTab.tsx` | Admin UI |

#### Configuration

Environment variables for scheduled tasks:

```bash
# Enable/disable scheduled task checking
SCHEDULED_TASK_CHECK_ENABLED=true

# Interval for checking due tasks (seconds)
SCHEDULED_TASK_CHECK_INTERVAL=60

# Lock timeout for task execution (seconds)
SCHEDULED_TASK_LOCK_TIMEOUT=300
```

#### Debugging Scheduled Tasks

```bash
# Check beat service logs
docker-compose logs -f beat

# Check worker logs for task execution
docker-compose logs -f worker | grep -i "scheduled\|maintenance"

# List active Celery tasks
docker exec -it curatore-worker celery -A app.celery_app inspect active

# Check scheduled task status in database
docker exec -it curatore-backend python -c "
from app.database.models import ScheduledTask
from app.services.database_service import database_service
import asyncio

async def check():
    async with database_service.get_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(ScheduledTask))
        for task in result.scalars():
            print(f'{task.name}: enabled={task.enabled}, next_run={task.next_run_at}')

asyncio.run(check())
"
```

### Extraction Engines

Curatore supports multiple extraction engines with content-type-based routing:

| Content Type | Extraction Engine | Notes |
|--------------|-------------------|-------|
| HTML (web pages) | **Playwright** | Inline extraction during crawl |
| PDF, DOCX, PPTX | **Extraction Service** or **Docling** | Separate extraction job |
| Images | **Extraction Service** (Tesseract OCR) | Separate extraction job |

**Content-Type Routing** (automatic):
- HTML content (`text/html`) is extracted inline by Playwright during web crawl
- Binary files (PDF, DOCX, etc.) go through the normal extraction pipeline
- Routing is handled automatically by `upload_integration_service.trigger_extraction()`

**Extraction Service** (`extraction-service/`):
- Standalone FastAPI microservice on port 8010
- Handles PDF, DOCX, PPTX, TXT, Images with OCR
- Uses MarkItDown and Tesseract for conversions
- Endpoint: `POST /api/v1/extract`

**Playwright Service** (`playwright-service/`):
- Browser-based rendering for JavaScript-heavy web scraping
- Standalone FastAPI microservice on port 8011
- Inline extraction: content is extracted during crawl (no separate job)
- Uses Chromium via Playwright for full JS rendering
- Extracts: HTML, markdown, links, document links
- Endpoint: `POST /api/v1/render`
- Configured via `PLAYWRIGHT_SERVICE_URL` (default: `http://playwright:8011`)

**Docling** (optional):
- External image/document converter
- Configured via `DOCLING_SERVICE_URL` (default: `http://docling:5001`)
- Endpoint: `POST /v1/convert/file`
- Enable in docker-compose: `ENABLE_DOCLING_SERVICE=true`

### Multi-Tenancy & Authentication

Curatore v2 supports multi-tenant architecture with optional authentication:

**Database Models**:
- **Organization**: Tenant with isolated settings and connections
- **User**: User accounts with email verification and password reset
- **ApiKey**: API keys for headless/programmatic access
- **Connection**: Runtime-configurable service connections (SharePoint, LLM, etc.)
- **SystemSetting**: Global system settings
- **AuditLog**: Audit trail for configuration changes

**Authentication Modes**:
- **`ENABLE_AUTH=false`** (default): Backward compatibility mode
  - No authentication required
  - Uses `DEFAULT_ORG_ID` from env or first organization in database
  - All requests operate in context of default organization

- **`ENABLE_AUTH=true`**: Multi-tenant mode with authentication
  - JWT token-based authentication (for frontend users)
  - API key authentication (for programmatic access)
  - Per-organization isolation of settings, connections, and users
  - Email verification and password reset workflows

**Initial Setup** (when using authentication):
1. Copy `.env.example` to `.env` and configure database settings
2. Run database initialization: `python -m app.commands.seed --create-admin`
3. Set `ENABLE_AUTH=true` in `.env`
4. Login with admin credentials and change password
5. Create organizations, users, and API keys as needed

**Important Files**:
- `backend/app/database/models.py`: ORM models for multi-tenant data
- `backend/app/commands/seed.py`: Database seeding and admin user creation
- `backend/app/services/auth_service.py`: JWT and API key handling
- `backend/app/dependencies.py`: Authentication dependency injection

### File Storage

#### Object Storage (S3/MinIO) - REQUIRED

**Curatore v2 now requires object storage** - filesystem storage has been removed. All files are stored in S3-compatible object storage (MinIO for development, AWS S3 for production).

**BREAKING CHANGE (v2.3+):** Local filesystem storage has been completely removed. The `/app/files` directory is no longer used.

**Architecture (v2.3+):**
```
Frontend → Backend API → MinIO/S3
                ↓
         proxy upload/download (all files stream through backend)
```

**BREAKING CHANGE (v2.3+):** All file operations are now proxied through the backend. Presigned URLs are deprecated but still available for backward compatibility.

**Object Storage Structure (v2.4+):**

Storage paths are now **human-readable and navigable**, organized by content source:

```
curatore-uploads/                              # Raw/source files
└── {org_id}/
    ├── uploads/                               # File uploads (UUID-based)
    │   └── {asset_uuid}/
    │       └── {filename}
    │
    ├── scrape/                                # Web scraping (collection-based)
    │   └── {collection_slug}/
    │       ├── pages/                         # Scraped web pages
    │       │   ├── _index.html               # Root page (/)
    │       │   ├── about.html                # /about
    │       │   ├── article/                  # /article/*
    │       │   │   ├── some-article.html
    │       │   │   └── another-article.html
    │       │   └── services/
    │       │       └── consulting.html
    │       │
    │       └── documents/                     # Downloaded documents
    │           ├── capability-statement.pdf
    │           └── quarterly-report.docx
    │
    └── sharepoint/                            # SharePoint (folder-based)
        └── {site_name}/
            └── {folder_path}/
                └── {filename}

curatore-processed/                            # Extracted markdown (mirrors structure)
└── {org_id}/
    ├── uploads/
    │   └── {asset_uuid}/
    │       └── {filename}.md
    │
    └── scrape/
        └── {collection_slug}/
            ├── pages/
            │   ├── _index.md
            │   ├── about.md
            │   └── article/
            │       └── some-article.md
            │
            └── documents/
                └── capability-statement.md

curatore-temp/                                 # Temporary processing files
└── {org_id}/
    └── {hash_prefix}/
        └── {filename}
```

**Key Service**: `backend/app/services/storage_path_service.py`

```python
from app.services.storage_path_service import storage_paths

# Web scraping paths
raw_html = storage_paths.scrape_page(org_id, "amivero", url)
extracted_md = storage_paths.scrape_page(org_id, "amivero", url, extracted=True)
doc_path = storage_paths.scrape_document(org_id, "amivero", "report.pdf")

# Upload paths (UUID-based for deduplication)
upload_path = storage_paths.upload(org_id, asset_id, "document.pdf")

# SharePoint paths (preserves folder structure)
sp_path = storage_paths.sharepoint(org_id, "MySite", "Documents/Reports", "q4.xlsx")
```

**Key Features:**
- **Provider-agnostic**: Works with MinIO (development) or AWS S3 (production)
- **Backend-proxied access (v2.3+)**: All file operations stream through backend API - eliminates need for direct browser-to-MinIO communication
- **Simplified configuration**: No environment-specific endpoints or /etc/hosts entries required
- **Artifact tracking**: Database tracks all stored files via the `Artifact` model
- **S3 lifecycle policies**: Automatic file expiration and retention (no Celery cleanup tasks needed)
- **Multi-bucket setup**: Separate buckets for uploads, processed files, and temp files
- **Multi-tenant isolation**: Organization ID prefixes ensure tenant isolation
- **Integrated MinIO SDK**: Direct connection from backend (no separate microservice needed)

**Setup (Development):**
1. MinIO starts automatically with backend services (no profile needed)
2. Run `./scripts/init_storage.sh` to create buckets and set lifecycle policies

**Note (v2.3+):** No `/etc/hosts` entries or `MINIO_PUBLIC_ENDPOINT` configuration required. All file access is proxied through backend API.

**Configuration:**
- `USE_OBJECT_STORAGE`: Must be `true` (default: true, no filesystem fallback)
- `MINIO_ENDPOINT`: MinIO server endpoint for backend connections (default: minio:9000)
- `MINIO_ACCESS_KEY`: MinIO access key (default: minioadmin)
- `MINIO_SECRET_KEY`: MinIO secret key (default: minioadmin)
- `MINIO_BUCKET_UPLOADS`: Bucket for uploaded files
- `MINIO_BUCKET_PROCESSED`: Bucket for processed files
- `MINIO_BUCKET_TEMP`: Bucket for temporary files

**Deprecated (v2.3+):**
- `MINIO_PUBLIC_ENDPOINT`: No longer needed with proxy architecture
- `MINIO_PRESIGNED_ENDPOINT`: No longer needed with proxy architecture
- `MINIO_PUBLIC_SECURE`: No longer needed with proxy architecture

See `.env.example` for complete configuration options

**File Upload/Download Workflow (v2.3+):**
1. **Upload**: Frontend uploads file to `POST /api/v1/storage/upload/proxy`
2. **Backend Proxy**: Backend receives file and uploads to MinIO
3. **Artifact**: Backend creates artifact record in database for tracking
4. **Process**: Celery task downloads from MinIO, processes, uploads result back to MinIO
5. **Download**: Frontend requests file from `GET /api/v1/storage/object/download?bucket={bucket}&key={key}`
6. **Backend Proxy**: Backend fetches from MinIO and streams to frontend

**Legacy Workflow (deprecated):**
- Presigned URL endpoints still available for backward compatibility
- `POST /api/v1/storage/upload/presigned` and `POST /api/v1/storage/upload/confirm`
- `GET /api/v1/storage/download/{document_id}/presigned`
- `GET /api/v1/storage/object/presigned` (marked deprecated in OpenAPI docs)

**Key Files:**
- `backend/app/services/storage_path_service.py`: Human-readable path generation for all content types
- `backend/app/services/minio_service.py`: MinIO SDK integration
- `backend/app/services/artifact_service.py`: Database tracking for stored files
- `backend/app/api/v1/routers/storage.py`: Presigned URL endpoints
- `backend/app/commands/init_storage.py`: Bucket initialization command
- `scripts/init_storage.sh`: Storage initialization script

**API Endpoints:**
- `GET /api/v1/storage/health`: Check object storage status
- `POST /api/v1/storage/upload/proxy`: Upload file proxied through backend (recommended)
- `GET /api/v1/storage/object/download`: Download file proxied through backend (recommended)
- `POST /api/v1/storage/upload/presigned`: Get presigned URL for upload (deprecated)
- `POST /api/v1/storage/upload/confirm`: Confirm upload completed (deprecated)
- `GET /api/v1/storage/download/{document_id}/presigned`: Get presigned URL for download (deprecated)
- `GET /api/v1/storage/object/presigned`: Get presigned URL for any object (deprecated)

**Database Storage** (SQLite/PostgreSQL):
```
/app/data/
└── curatore.db          # SQLite database file (development)
```

**Important:**
- Object storage is **REQUIRED** - the system will not work without it
- MinIO starts automatically with backend services
- Run `./scripts/init_storage.sh` after first startup to initialize buckets
- For production, use AWS S3 or another S3-compatible service
- S3 lifecycle policies handle file retention (configured via init_storage command)

### Frontend Architecture

Next.js 15 App Router with TypeScript:

```
frontend/
├── app/                    # App Router pages and layouts
├── components/             # React components
├── lib/
│   └── api.ts             # API client with v1 endpoints
└── package.json
```

**API Client**: Uses `NEXT_PUBLIC_API_URL` environment variable (default: `http://localhost:8000`)

**Key Features**:
- Drag-and-drop file uploads
- Real-time processing status with emoji indicators
- Quality score monitoring and thresholds
- Batch processing and bulk downloads

### Frontend Design System

The frontend follows a modern enterprise design system. Use these patterns when updating or creating new pages to maintain visual consistency.

#### Reference Implementation

The **Connections page** (`frontend/app/connections/page.tsx`) serves as the reference implementation for the design system. When updating other pages, use this as the template.

**Key files demonstrating the design system:**
- `frontend/app/connections/page.tsx` - Page layout, headers, empty states, section organization
- `frontend/components/connections/ConnectionCard.tsx` - Card components with status indicators
- `frontend/components/connections/ConnectionForm.tsx` - Multi-step forms, input styling

#### Color Palette

**Primary Colors (Indigo/Purple theme):**
```
Primary gradient:     from-indigo-500 to-purple-600
Primary solid:        indigo-600 (buttons, active states)
Primary light:        indigo-50 (backgrounds), indigo-100 (hover)
Primary text:         indigo-600 (light mode), indigo-400 (dark mode)
```

**Semantic Colors:**
```
Success/Healthy:      emerald-500, emerald-50 (bg), emerald-600/400 (text)
Error/Unhealthy:      red-500, red-50 (bg), red-600/400 (text)
Warning/Managed:      amber-500, amber-50 (bg), amber-700/300 (text)
Info/Checking:        blue-500, blue-50 (bg), blue-600/400 (text)
Neutral:              gray-400/500, gray-50/800 (bg)
```

**Type-Specific Gradients:**
```
LLM:                  from-violet-500 to-purple-600
SharePoint:           from-blue-500 to-cyan-500
Extraction:           from-emerald-500 to-teal-500
```

#### Typography

```
Page title:           text-2xl sm:text-3xl font-bold
Section header:       text-lg font-semibold
Card title:           text-base font-semibold
Body text:            text-sm
Helper/meta text:     text-xs
Monospace values:     font-mono text-xs
```

#### Layout Patterns

**Page Container:**
```tsx
<div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    {/* Page content */}
  </div>
</div>
```

**Page Header with Icon:**
```tsx
<div className="flex items-center gap-4">
  <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
    <Icon className="w-6 h-6" />
  </div>
  <div>
    <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
      Page Title
    </h1>
    <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
      Page description
    </p>
  </div>
</div>
```

**Section Header with Count Badge:**
```tsx
<div className="flex items-center gap-4 mb-5">
  <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${gradient} flex items-center justify-center text-white shadow-lg`}>
    <Icon className="w-5 h-5" />
  </div>
  <div className="flex-1">
    <div className="flex items-center gap-3">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
        Section Title
      </h2>
      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
        {count}
      </span>
    </div>
    <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
      Section description
    </p>
  </div>
</div>
```

**Stats Bar (Pills):**
```tsx
<div className="flex flex-wrap items-center gap-4 text-sm">
  <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
    <span className="font-medium">{count}</span>
    <span>total</span>
  </div>
  <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
    <span className="font-medium">{healthyCount}</span>
    <span>healthy</span>
  </div>
</div>
```

#### Card Components

**Standard Card:**
```tsx
<div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200 overflow-hidden">
  {/* Status bar at top */}
  <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${statusGradient}`} />

  <div className="p-5">
    {/* Card content */}
  </div>
</div>
```

**Status Badge:**
```tsx
<div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${bgColor} ${textColor}`}>
  <StatusIcon className="w-4 h-4" />
  <span>{statusLabel}</span>
</div>
```

**Config/Value Display:**
```tsx
<div className="flex items-center justify-between text-sm">
  <span className="text-gray-500 dark:text-gray-400">Label</span>
  <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded truncate max-w-[180px]">
    {value}
  </span>
</div>
```

#### Empty States

```tsx
<div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
  {/* Background decoration */}
  <div className="absolute inset-0 pointer-events-none">
    <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
    <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
  </div>

  <div className="relative">
    <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-6">
      <Icon className="w-10 h-10 text-white" />
    </div>
    <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
      No items found
    </h3>
    <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-8">
      Description of what to do next
    </p>
    <Button onClick={handleCreate} size="lg" className="gap-2 shadow-lg shadow-blue-500/25">
      <Plus className="w-5 h-5" />
      Create first item
    </Button>
  </div>
</div>
```

#### Form Components

**Form Container (Modal/Panel):**
```tsx
<div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl overflow-hidden">
  {/* Gradient header */}
  <div className="relative bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 px-6 py-5">
    <h2 className="text-xl font-bold text-white">Form Title</h2>
    <p className="text-indigo-100 text-sm mt-0.5">Form description</p>
  </div>

  <div className="p-6">
    {/* Form content */}
  </div>
</div>
```

**Input Field:**
```tsx
<div className="space-y-1.5">
  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
    Field Label
  </label>
  <input
    type="text"
    className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition-all"
  />
</div>
```

**Toggle Switch:**
```tsx
<label className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-xl cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
  <div>
    <p className="text-sm font-medium text-gray-900 dark:text-white">Toggle Label</p>
    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Description</p>
  </div>
  <div className="relative">
    <input type="checkbox" className="sr-only peer" />
    <div className="w-11 h-6 bg-gray-200 peer-focus:ring-4 peer-focus:ring-indigo-300 dark:peer-focus:ring-indigo-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
  </div>
</label>
```

#### Step Indicator (Multi-step Forms)

```tsx
<div className="flex items-center justify-center mb-8">
  {steps.map((step, index) => (
    <div key={step.id} className="flex items-center">
      <div className="flex flex-col items-center">
        <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium transition-all ${
          index < currentStepIndex
            ? 'bg-indigo-600 text-white'
            : index === currentStepIndex
            ? 'bg-indigo-600 text-white ring-4 ring-indigo-100 dark:ring-indigo-900/50'
            : 'bg-gray-100 dark:bg-gray-800 text-gray-400'
        }`}>
          {index < currentStepIndex ? <Check className="w-4 h-4" /> : index + 1}
        </div>
        <span className={`mt-2 text-xs font-medium ${
          index <= currentStepIndex ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'
        }`}>
          {step.label}
        </span>
      </div>
      {index < steps.length - 1 && (
        <div className={`w-12 sm:w-16 h-0.5 mx-2 ${
          index < currentStepIndex ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700'
        }`} />
      )}
    </div>
  ))}
</div>
```

#### Dropdown Menu

```tsx
<div className="relative" ref={menuRef}>
  <button className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all">
    <MoreHorizontal className="w-4 h-4" />
  </button>

  {showMenu && (
    <div className="absolute right-0 top-full mt-1 w-40 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 z-10">
      <button className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
        <Pencil className="w-4 h-4" />
        Edit
      </button>
      <hr className="my-1 border-gray-200 dark:border-gray-700" />
      <button className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors">
        <Trash2 className="w-4 h-4" />
        Delete
      </button>
    </div>
  )}
</div>
```

#### Icons

Use **Lucide React** icons consistently:
```tsx
import {
  // Navigation/Actions
  Plus, Pencil, Trash2, MoreHorizontal, RefreshCw, X, ChevronRight,
  // Status
  CheckCircle, XCircle, AlertCircle, AlertTriangle, Loader2,
  // Features
  Link2, Zap, FolderSync, FileText, Star, ExternalLink, Check
} from 'lucide-react'
```

#### Loading States

**Spinner:**
```tsx
<div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
```

**Loading Page:**
```tsx
<div className="flex flex-col items-center justify-center py-16">
  <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
  <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading...</p>
</div>
```

#### Error States

```tsx
<div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
  <div className="flex items-center gap-3">
    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
      <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
    </div>
    <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
  </div>
</div>
```

#### Dark Mode

All components must support dark mode using Tailwind's `dark:` prefix. Key patterns:
- Backgrounds: `bg-white dark:bg-gray-800` or `bg-gray-50 dark:bg-gray-900`
- Borders: `border-gray-200 dark:border-gray-700`
- Text: `text-gray-900 dark:text-white` (primary), `text-gray-500 dark:text-gray-400` (secondary)
- Hover states: `hover:bg-gray-100 dark:hover:bg-gray-700`

#### Responsive Design

- Use mobile-first approach with `sm:`, `md:`, `lg:`, `xl:` breakpoints
- Hide/show elements: `hidden sm:inline` or `sm:hidden`
- Responsive grids: `grid-cols-1 md:grid-cols-2 xl:grid-cols-3`
- Responsive spacing: `px-4 sm:px-6 lg:px-8`

#### Migration Checklist

When updating a page to match the design system:

1. [ ] Update page container with gradient background
2. [ ] Add page header with gradient icon
3. [ ] Add stats bar if applicable
4. [ ] Update section headers with icons and count badges
5. [ ] Redesign cards with status indicator bars
6. [ ] Add dropdown menus for card actions
7. [ ] Update empty states with illustration
8. [ ] Update forms with gradient headers
9. [ ] Update input field styling
10. [ ] Add proper loading and error states
11. [ ] Verify dark mode support
12. [ ] Test responsive behavior

**Pages to Update:**
- [ ] `/` (Dashboard/Home)
- [ ] `/process` (Document Processing)
- [ ] `/jobs` (Job List)
- [ ] `/jobs/[id]` (Job Details)
- [ ] `/settings-admin` (Admin Settings - includes Users tab)
- [ ] `/storage` (Storage Management)
- [x] `/connections` (Reference implementation)

## Development Patterns

### Making Changes to the Processing Pipeline

1. **Document Service** (`backend/app/services/document_service.py`):
   - Core processing logic for document conversion
   - Uses extraction service for actual conversion
   - Handles quality assessment and optimization

2. **Extraction Service** (`extraction-service/app/services/extraction_service.py`):
   - Low-level conversion using MarkItDown and Tesseract
   - Handles supported file types and OCR

3. **Worker Task** (`backend/app/tasks.py`):
   - Celery task wrapper that orchestrates the pipeline
   - Manages job status and error handling

### Adding New API Endpoints

1. Create endpoint in appropriate router (`backend/app/api/v1/routers/`)
2. Define request/response models in `backend/app/api/v1/models.py`
3. Implement business logic in service layer (`backend/app/services/`)
4. Add authentication dependencies if needed (`from app.dependencies import get_current_user`)
5. Update frontend API client if needed (`frontend/lib/api.ts`)

### Working with Runtime-Configurable Connections

When `ENABLE_AUTH=true`, external service connections (SharePoint, LLM, etc.) can be managed at runtime per organization:

**Connection Types**:
- `sharepoint`: Microsoft SharePoint/Graph API connection
- `llm`: OpenAI-compatible LLM API connection (OpenAI, Ollama, LM Studio, etc.)
- `extraction`: Document extraction service connection (extraction-service or Docling)
- `playwright`: Playwright rendering service for JavaScript-heavy web scraping
- Custom types can be added by extending the BaseConnectionType class

**Typical Flow**:
1. User creates connection via `POST /api/v1/connections` with credentials
2. Backend optionally tests connection health on save (`AUTO_TEST_CONNECTIONS=true`)
3. Services fetch active connection for organization from database
4. If no connection exists, fall back to environment variables

**Important**:
- Credentials are stored encrypted in the database
- Each organization has isolated connections
- Connection health can be tested via `POST /api/v1/connections/{id}/test`
- Services should gracefully fall back to env vars when no connection exists

### Testing Strategy

**Backend Tests** (`backend/tests/`):
- Use pytest with session-scoped fixtures
- Tests run in isolated temp directory (`conftest.py` handles setup)
- Mock external services (LLM, extraction) when appropriate
- Run from project root: `pytest backend/tests`

**Extraction Service Tests** (`extraction-service/tests/`):
- Generate synthetic test files (DOCX, PDF, XLSX) at runtime
- Test all supported formats and corruption cases
- Validate OCR fallback behavior
- Run with: `pytest extraction-service/tests`

**Frontend Tests**:
- Standard Next.js testing patterns
- Run with: `cd frontend && npm test`

### Hot Reload Behavior

- **Backend & Extraction**: Uvicorn `--reload` watches Python files
- **Worker**: `watchmedo` auto-restarts on `.py` changes
- **Frontend**: Next.js Turbopack provides fast refresh

**When to Rebuild**:
- Changed `requirements.txt`: `./scripts/dev-restart.sh --build backend worker`
- Changed `package.json`: `./scripts/dev-restart.sh --build frontend`
- Changed Dockerfiles: `./scripts/dev-restart.sh --build <service>`

## Configuration

### Environment Variables

Key environment variables (see `.env.example` for full list):

**LLM Configuration**:
- `OPENAI_API_KEY`: API key for LLM
- `OPENAI_MODEL`: Model name (default: `gpt-4o-mini`)
- `OPENAI_BASE_URL`: API endpoint (supports Ollama, OpenWebUI, LM Studio)

**Extraction**:
- `EXTRACTION_SERVICE_URL`: Default extraction service URL
- `DOCLING_SERVICE_URL`: Docling service URL (when using Docling)

**Queue**:
- `CELERY_BROKER_URL`: Redis broker URL (default: `redis://redis:6379/0`)
- `CELERY_RESULT_BACKEND`: Redis results URL (default: `redis://redis:6379/1`)
- `CELERY_DEFAULT_QUEUE`: Queue name (default: `processing`)

**Quality Thresholds**:
- `DEFAULT_CONVERSION_THRESHOLD`: 0-100 scale (default: 70)
- `DEFAULT_CLARITY_THRESHOLD`: 1-10 scale (default: 7)
- `DEFAULT_COMPLETENESS_THRESHOLD`: 1-10 scale (default: 7)
- `DEFAULT_RELEVANCE_THRESHOLD`: 1-10 scale (default: 7)
- `DEFAULT_MARKDOWN_THRESHOLD`: 1-10 scale (default: 7)

**SharePoint / Microsoft Graph**:
- `MS_TENANT_ID`: Azure AD tenant ID (GUID format)
- `MS_CLIENT_ID`: Azure AD app registration client ID
- `MS_CLIENT_SECRET`: Azure AD app registration client secret
- `MS_GRAPH_SCOPE`: OAuth scope (default: `https://graph.microsoft.com/.default`)
- `MS_GRAPH_BASE_URL`: Graph API base URL (default: `https://graph.microsoft.com/v1.0`)

**Database**:
- `DATABASE_URL`: SQLAlchemy connection URL
  - SQLite (dev): `sqlite+aiosqlite:///./data/curatore.db`
  - PostgreSQL (prod): `postgresql+asyncpg://user:pass@host:5432/curatore`
- `DB_POOL_SIZE`: Connection pool size (PostgreSQL, default: 20)
- `DB_MAX_OVERFLOW`: Max overflow connections (PostgreSQL, default: 40)
- `DB_POOL_RECYCLE`: Connection recycle time in seconds (PostgreSQL, default: 3600)

**Authentication & Security**:
- `ENABLE_AUTH`: Enable authentication layer (default: `false`)
- `DEFAULT_ORG_ID`: Default organization UUID (when `ENABLE_AUTH=false`)
- `JWT_SECRET_KEY`: Secret key for JWT signing (change in production!)
- `JWT_ALGORITHM`: JWT signing algorithm (default: `HS256`)
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: Access token TTL (default: 60)
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS`: Refresh token TTL (default: 30)
- `BCRYPT_ROUNDS`: Bcrypt work factor (default: 12)
- `API_KEY_PREFIX`: API key prefix for display (default: `cur_`)

**Email Configuration**:
- `EMAIL_BACKEND`: Email backend (`console`, `smtp`, `sendgrid`, `ses`)
- `EMAIL_FROM_ADDRESS`: From email address
- `EMAIL_FROM_NAME`: From display name
- `FRONTEND_BASE_URL`: Frontend URL for verification/reset links
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: SMTP settings (when using `smtp`)
- `SENDGRID_API_KEY`: SendGrid API key (when using `sendgrid`)
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: AWS SES settings (when using `ses`)
- `EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS`: Verification token TTL (default: 24)
- `PASSWORD_RESET_TOKEN_EXPIRE_HOURS`: Reset token TTL (default: 1)
- `EMAIL_VERIFICATION_GRACE_PERIOD_DAYS`: Grace period before enforcing verification (default: 7)

**Initial Seeding** (first-time setup):
- `ADMIN_EMAIL`: Initial admin email
- `ADMIN_USERNAME`: Initial admin username
- `ADMIN_PASSWORD`: Initial admin password (change after first login!)
- `ADMIN_FULL_NAME`: Initial admin full name
- `DEFAULT_ORG_NAME`: Default organization name
- `DEFAULT_ORG_SLUG`: Default organization slug

## YAML Configuration System

Curatore v2 supports YAML-based service configuration as the recommended approach (v2.1+). Services automatically load from `config.yml` with fallback to environment variables for backward compatibility.

### Configuration Priority

1. **config.yml** (if present) - Structured YAML at project root
2. **Environment variables** - From `.env` or system environment
3. **Built-in defaults** - Sensible defaults in Pydantic models

### Quick Setup

```bash
# Copy example configuration
cp config.yml.example config.yml

# Edit with your service credentials
# Use ${VAR_NAME} to reference secrets from .env

# Validate configuration
python -m app.commands.validate_config

# Start services (config.yml is mounted read-only)
docker-compose up -d
```

### Configuration Structure

**File**: `config.yml` (project root)

```yaml
version: "2.0"

# LLM Service Configuration
llm:
  provider: openai  # openai | ollama | openwebui | lmstudio
  api_key: ${OPENAI_API_KEY}  # Reference from .env
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  timeout: 60
  max_retries: 3
  temperature: 0.7
  verify_ssl: true

# Extraction Service Configuration
extraction:
  priority: default  # default | docling | auto | none
  services:
    - name: extraction-service
      url: http://extraction:8010
      timeout: 300
      enabled: true
    - name: docling
      url: http://docling:5001
      timeout: 600
      enabled: false

# Microsoft SharePoint Configuration
sharepoint:
  enabled: true
  tenant_id: ${MS_TENANT_ID}
  client_id: ${MS_CLIENT_ID}
  client_secret: ${MS_CLIENT_SECRET}
  graph_scope: https://graph.microsoft.com/.default
  graph_base_url: https://graph.microsoft.com/v1.0

# Email Service Configuration
email:
  backend: smtp  # console | smtp | sendgrid | ses
  from_address: noreply@curatore.example.com
  from_name: Curatore
  smtp:
    host: smtp.gmail.com
    port: 587
    username: ${SMTP_USERNAME}
    password: ${SMTP_PASSWORD}
    use_tls: true

# Storage Configuration
storage:
  hierarchical: true
  deduplication:
    enabled: true
    strategy: symlink  # symlink | copy | reference
  retention:
    uploaded_days: 7
    processed_days: 30
  cleanup:
    enabled: true
    schedule_cron: "0 2 * * *"

# Queue Configuration
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
  default_queue: processing
  worker_concurrency: 4
```

### Environment Variable References

Use `${VAR_NAME}` syntax to reference secrets from `.env`:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}  # Resolves from .env or environment

sharepoint:
  tenant_id: ${MS_TENANT_ID}
  client_secret: ${MS_CLIENT_SECRET}
```

**Benefits:**
- Keep secrets in `.env` (not committed to Git)
- Share `config.yml` structure across environments
- Override specific values per environment

### Using Config Loader in Services

**File**: `backend/app/services/config_loader.py`

```python
from app.services.config_loader import config_loader

# Load configuration
config = config_loader.get_config()

# Get typed configuration
llm_config = config_loader.get_llm_config()  # Returns LLMConfig | None
extraction_config = config_loader.get_extraction_config()
sharepoint_config = config_loader.get_sharepoint_config()

# Get value by dot notation
api_key = config_loader.get("llm.api_key", default="fallback")
timeout = config_loader.get("llm.timeout", default=60)

# Reload configuration (without restart)
config_loader.reload()
```

### Service Integration Pattern

Services should try loading from config.yml first, then fall back to environment variables:

```python
# Example: backend/app/services/llm_service.py
import logging
from ..services.config_loader import config_loader

logger = logging.getLogger(__name__)

def _initialize_client(self):
    # Try loading from config.yml first
    llm_config = config_loader.get_llm_config()

    if llm_config:
        logger.info("Loading LLM configuration from config.yml")
        api_key = llm_config.api_key
        base_url = llm_config.base_url
        timeout = llm_config.timeout
    else:
        # Fallback to environment variables
        logger.info("Loading LLM configuration from environment variables")
        api_key = settings.openai_api_key
        base_url = settings.openai_base_url
        timeout = settings.openai_timeout

    # Initialize client...
```

**Benefits:**
- Backward compatibility (existing .env still works)
- Clear logging of configuration source
- Graceful degradation

### Configuration Validation

Validate configuration before starting services:

```bash
# Validate config.yml
python -m app.commands.validate_config

# Output:
✓ config.yml found and readable
✓ YAML syntax valid
✓ Schema validation passed
✓ Environment variables resolved
✓ LLM configuration valid
✓ Extraction configuration valid
✓ SharePoint configuration valid
✓ Email configuration valid
✓ All services reachable

Configuration is valid!

# Skip connectivity tests
python -m app.commands.validate_config --skip-connectivity

# Specify custom config file
python -m app.commands.validate_config --config-path config.dev.yml
```

### Migrating from .env to config.yml

Automated migration script:

```bash
# Generate config.yml from .env
python scripts/migrate_env_to_yaml.py

# Output:
Reading .env file: .env
Found 25 environment variables

Generated config.yml with:
  ✓ LLM configuration (OpenAI)
  ✓ Extraction services (2 services)
  ✓ SharePoint configuration
  ✓ Email configuration (SMTP)
  ✓ Storage configuration
  ✓ Queue configuration

Successfully created config.yml

# Dry-run mode (print without writing)
python scripts/migrate_env_to_yaml.py --dry-run

# Custom paths
python scripts/migrate_env_to_yaml.py --env-file .env.prod --output config.prod.yml
```

**Migration process:**
1. Parses `.env` file
2. Infers provider types from URLs
3. Generates structured YAML
4. Uses `${VAR_NAME}` for sensitive values
5. Preserves secrets in `.env`

### Configuration Models

**File**: `backend/app/models/config_models.py`

Pydantic v2 models provide type-safe validation:

```python
from app.models.config_models import (
    AppConfig,      # Root configuration
    LLMConfig,      # LLM service
    ExtractionConfig,
    SharePointConfig,
    EmailConfig,
    StorageConfig,
    QueueConfig,
)

# Load and validate from YAML
config = AppConfig.from_yaml("config.yml")

# Access typed values
if config.llm:
    print(f"LLM Provider: {config.llm.provider}")
    print(f"Model: {config.llm.model}")
    print(f"Timeout: {config.llm.timeout}s")

# Validation errors are raised on invalid config
```

**Model features:**
- Type validation with Pydantic Field validators
- Default values for optional settings
- Environment variable resolution
- Extra field prevention (strict mode)
- Comprehensive error messages

### Multiple Environments

Use different config files per environment:

```bash
# Development
cp config.yml.example config.dev.yml
export CONFIG_PATH=config.dev.yml

# Production
cp config.yml.example config.prod.yml
export CONFIG_PATH=config.prod.yml

# Validate specific config
python -m app.commands.validate_config --config-path config.prod.yml

# Mount in Docker
docker run -v ./config.prod.yml:/app/config.yml:ro curatore-backend
```

### Testing Configuration

**File**: `backend/tests/test_config_loader.py`

Test coverage includes:
- Valid configuration loading
- Environment variable resolution
- Missing environment variables
- Invalid YAML syntax
- Schema validation
- Typed getters
- Configuration reload
- Optional service configs

```bash
# Run config tests
pytest backend/tests/test_config_loader.py -v
```

### Documentation

Complete configuration reference: **[docs/CONFIGURATION.md](./docs/CONFIGURATION.md)**

Includes:
- Getting started guide
- Complete service configuration reference
- Environment variable references
- Troubleshooting guide
- Migration guide
- Advanced topics (hot reloading, multiple environments)

## Common Development Tasks

### Database Setup and Seeding

When using multi-tenancy and authentication features:

```bash
# Initialize database and create admin user
python -m app.commands.seed --create-admin

# The seed command:
# 1. Creates database tables (if not exist)
# 2. Creates default organization from env vars
# 3. Creates admin user with credentials from env vars
# 4. Returns organization ID and admin user ID

# After seeding, set ENABLE_AUTH=true in .env to enable authentication
```

**Important**:
- Run the seed command before enabling authentication
- Change the default admin password immediately after first login
- Store `DEFAULT_ORG_ID` from seed output in `.env` for backward compatibility mode

### Debugging Processing Failures

1. Check worker logs: `./scripts/tail_worker.sh`
2. Check job status: `curl http://localhost:8000/api/v1/jobs/{job_id}`
3. Check job logs: Job status response includes `logs` array
4. Test extraction directly: `curl -X POST http://localhost:8010/api/v1/extract -F "file=@test.pdf"`

### Debugging Queue Issues

1. Check queue health: `./scripts/queue_health.sh`
2. Check Redis: `docker exec -it curatore-redis redis-cli`
3. List pending jobs: `celery -A app.celery_app inspect active`
4. Purge queue: `celery -A app.celery_app purge`

### Testing LLM Integration

```bash
# Check LLM status
curl http://localhost:8000/api/v1/llm/status

# Test with different LLM providers by changing .env:
# Ollama:    OPENAI_BASE_URL=http://localhost:11434/v1
# OpenWebUI: OPENAI_BASE_URL=http://localhost:3000/v1
# LM Studio: OPENAI_BASE_URL=http://localhost:1234/v1
```

### Adding Support for New File Types

1. Update `extraction-service/app/services/extraction_service.py`
2. Add conversion method in extraction service
3. Update fallback chain if needed
4. Add test cases in `extraction-service/tests/`
5. Update supported formats in backend config

### SharePoint Integration Workflow

The SharePoint integration allows you to list and download files from SharePoint directly into Curatore for processing:

**Setup Requirements**:
1. Azure AD app registration with client credentials
2. Microsoft Graph API permissions: `Sites.Read.All` or `Files.Read.All`
3. Grant admin consent for the application
4. Configure environment variables: `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`

**Typical Workflow**:

1. **Inventory**: List files in a SharePoint folder
   ```bash
   curl -X POST http://localhost:8000/api/v1/sharepoint/inventory \
     -H "Content-Type: application/json" \
     -d '{
       "folder_url": "https://tenant.sharepoint.com/sites/docs/Shared Documents/folder",
       "recursive": false,
       "include_folders": false,
       "page_size": 200
     }'
   ```

   Returns indexed list of files with metadata (name, type, size, modified date, etc.)

2. **Download**: Download selected files to batch directory
   ```bash
   curl -X POST http://localhost:8000/api/v1/sharepoint/download \
     -H "Content-Type: application/json" \
     -d '{
       "folder_url": "https://tenant.sharepoint.com/sites/docs/Shared Documents/folder",
       "indices": [1, 3, 5],
       "preserve_folders": true
     }'
   ```

   Files are downloaded to `/app/files/batch_files` and ready for batch processing

3. **Process**: Use existing batch processing endpoints to process downloaded files
   ```bash
   curl -X POST http://localhost:8000/api/v1/documents/batch/process
   ```

**Script Integration**:

Helper scripts in `scripts/sharepoint/` provide standalone functionality:
- `sharepoint_connect.py`: Test connectivity and authentication
- `sharepoint_inventory.py`: List folder contents
- `sharepoint_download.py`: Download files with selection
- `sharepoint_process.py`: End-to-end workflow (inventory, download, process)
- `graph_client.py`: Reusable Microsoft Graph API helpers
- `inventory_utils.py`: Shared utilities for inventory operations

**Key Features**:
- Recursive folder traversal
- Selective file downloads by index
- Folder structure preservation
- Duplicate detection (skips already-downloaded files)
- Pagination support for large folders
- Automatic OAuth token management

### SAM.gov Integration (Phase 7)

SAM.gov integration enables searching, tracking, and analyzing federal contract opportunities:

**Key Features:**
- Search for opportunities by NAICS codes, PSC codes, agencies, keywords
- Track solicitations and amendments over time
- Download attachments and trigger automatic extraction
- Generate LLM-powered summaries with compliance checklists
- API rate limit tracking (1,000 calls/day) with usage display
- Request queuing when over rate limit
- Attachment deduplication by download URL

**Important: Broad Search Strategy**

The SAM.gov Opportunities API v2 has limited filtering capabilities. In particular:
- You cannot filter by multiple NAICS codes in a single API call
- Some filter combinations are not supported

Because of these limitations, Curatore uses a "broad search, post-filter" approach:
1. **API Searches are broad**: Fetches more results than strictly needed
2. **Filtering happens in UI**: The frontend applies additional filters to narrow down results
3. **Use `search_config` for client-side filtering**: Store filter criteria like multiple NAICS codes in `search_config`, but don't expect the API to enforce all of them

**API Rate Limits:**
- SAM.gov enforces a 1,000 API calls per day limit
- Curatore tracks usage automatically via `SamApiUsage` model
- The UI shows current usage and remaining calls
- When limits are exceeded, requests are queued for the next day via `SamQueuedRequest`

**SamSearch Configuration Options:**
```json
{
  "naics_codes": ["541512", "541519"],    // Multiple NAICS for post-filtering
  "psc_codes": ["D302"],                   // PSC codes
  "set_aside_codes": ["SBA", "8A"],        // Set-aside types
  "agencies": ["DEPT OF DEFENSE"],         // Agency filter
  "notice_types": ["o", "p", "k"],         // Notice types to include
  "keyword": "software",                   // Keyword search
  "posted_from": "2024-01-01",             // Date range
  "active_only": true,                     // Only active opportunities
  "download_attachments": true             // Whether to track attachments for download
}
```

**Database Models:**
| Model | Purpose |
|-------|---------|
| `SamSearch` | Top-level search configuration (like ScrapeCollection) |
| `SamSolicitation` | Individual opportunity tracking |
| `SamNotice` | Version history (amendments, modifications) |
| `SamAttachment` | Links to downloaded Assets |
| `SamSolicitationSummary` | LLM-generated analysis |
| `SamAgency`, `SamSubAgency` | Reference data for agencies |

**API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sam/searches` | List SAM searches |
| POST | `/sam/searches` | Create search |
| POST | `/sam/searches/preview` | Preview/test search config |
| GET | `/sam/searches/{id}` | Get search details |
| PATCH | `/sam/searches/{id}` | Update search |
| DELETE | `/sam/searches/{id}` | Archive search |
| POST | `/sam/searches/{id}/pull` | Trigger pull from SAM.gov |
| GET | `/sam/solicitations` | List solicitations |
| GET | `/sam/solicitations/{id}` | Get solicitation details |
| POST | `/sam/solicitations/{id}/summarize` | Generate LLM summary |
| GET | `/sam/notices/{id}` | Get notice details |
| POST | `/sam/attachments/{id}/download` | Download attachment |
| GET | `/sam/usage` | Get today's API usage |
| GET | `/sam/usage/history` | Get usage history |
| POST | `/sam/usage/estimate` | Estimate API impact of search |
| GET | `/sam/usage/status` | Get full API status for dashboard |
| GET | `/sam/queue` | Get queue statistics |

**Celery Tasks:**
- `sam_pull_task(search_id)` - Fetch data from SAM.gov API
- `sam_download_attachment_task(attachment_id)` - Download single attachment
- `sam_summarize_task(solicitation_id, config)` - Generate LLM summary
- `sam_batch_summarize_task(search_id)` - Summarize multiple solicitations
- `sam_process_queued_requests_task()` - Process queued requests (runs every 5 min)

**Configuration:**
```bash
# Required
SAM_API_KEY=your_api_key_from_api.sam.gov

# Optional
SAM_ENABLED=true
SAM_BASE_URL=https://api.sam.gov/opportunities/v2
SAM_TIMEOUT=60
SAM_RATE_LIMIT_DELAY=0.5

# Queue processing (for rate-limited requests)
SAM_QUEUE_PROCESS_ENABLED=true
SAM_QUEUE_PROCESS_INTERVAL=300  # Every 5 minutes
```

**Typical Workflow:**
1. Create a search with filters (NAICS codes, agencies, etc.)
2. Trigger a pull to fetch opportunities from SAM.gov
3. Review solicitations in the UI
4. Download attachments (creates Assets, triggers extraction)
5. Generate summaries with LLM analysis

**Storage Structure:**
```
curatore-uploads/
└── {org_id}/
    └── sam/
        └── solicitations/
            └── {solicitation_number}/
                └── attachments/
                    ├── sow.pdf
                    └── pricing.xlsx

curatore-processed/
└── {org_id}/
    └── sam/
        └── solicitations/
            └── {solicitation_number}/
                └── attachments/
                    ├── sow.md
                    └── pricing.md
```

### Web Scraping with Playwright

Curatore uses Playwright for JavaScript-rendered web scraping with inline content extraction.

**Key Features**:
- Full JavaScript rendering via Chromium browser
- Inline extraction: Markdown is extracted during crawl (no separate job)
- Automatic document discovery: Finds PDFs, DOCXs linked on pages
- Content-type routing: HTML → Playwright, binary files → Docling

**ScrapeCollection crawl_config Schema**:

```json
{
  // Crawl behavior
  "max_depth": 3,                    // Maximum link-following depth
  "max_pages": 100,                  // Maximum pages to crawl
  "delay_seconds": 1.0,              // Rate limiting between requests
  "follow_external_links": false,    // Stay on same domain

  // Playwright rendering options
  "wait_for_selector": ".main-content",  // CSS selector to wait for
  "wait_timeout_ms": 5000,               // Wait timeout (ms)
  "viewport_width": 1920,                // Browser viewport width
  "viewport_height": 1080,               // Browser viewport height
  "render_timeout_ms": 30000,            // Total render timeout (ms)

  // Document discovery
  "download_documents": false,           // Auto-download discovered PDFs/DOCXs
  "document_extensions": [".pdf", ".docx", ".doc", ".xlsx", ".pptx"]
}
```

**Crawl Workflow**:

1. **Create Collection**: Define seed URLs and crawl config
2. **Playwright Renders**: Page is loaded with full JS execution
3. **Inline Extraction**: HTML → Markdown during crawl (no queue)
4. **Asset Created**: Asset status = "ready" immediately
5. **Documents Discovered**: If `download_documents=true`, PDFs are downloaded
6. **Binary Extraction**: Downloaded documents go through Docling pipeline

**Environment Variables**:
- `PLAYWRIGHT_SERVICE_URL`: Playwright service endpoint (default: `http://playwright:8011`)
- `PLAYWRIGHT_TIMEOUT`: Request timeout in seconds (default: `60`)

### Job Management Workflow

The job management system provides batch document processing with tracking, concurrency control, and retention policies:

**Key Concepts**:
- **Job**: A batch of documents processed together with shared options
- **Job Document**: Individual document within a job with its own status tracking
- **Job Lifecycle**: PENDING → QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED
- **Concurrency Limit**: Per-organization limit prevents resource exhaustion (default: 3)
- **Retention Policy**: Auto-cleanup after configurable days (7/30/90/indefinite)

**Typical Workflow**:

1. **Create Job**: Batch multiple documents into a tracked job
   ```bash
   curl -X POST http://localhost:8000/api/v1/jobs \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "document_ids": ["doc-123", "doc-456", "doc-789"],
       "options": {
         "quality_thresholds": {
           "conversion_threshold": 70.0,
           "clarity_threshold": 7.0
         },
         "ocr_settings": {
           "enabled": true,
           "language": "eng"
         }
       },
       "name": "Q4 Report Processing",
       "description": "Process Q4 financial reports",
       "start_immediately": true
     }'
   ```

   Returns job ID and starts processing immediately if `start_immediately=true`

2. **Monitor Progress**: Poll job status for real-time updates
   ```bash
   curl http://localhost:8000/api/v1/jobs/{job_id} \
     -H "Authorization: Bearer $TOKEN"
   ```

   Response includes:
   - Overall job status
   - Document-level progress (completed/failed counts)
   - Processing logs
   - Quality metrics and results

3. **Cancel Job** (if needed): Immediate termination with cleanup
   ```bash
   curl -X POST http://localhost:8000/api/v1/jobs/{job_id}/cancel \
     -H "Authorization: Bearer $TOKEN"
   ```

   Verification ensures:
   - Celery tasks revoked
   - Partial files deleted
   - Job status updated to CANCELLED

4. **View Organization Stats** (admins only): Org-wide job metrics
   ```bash
   curl http://localhost:8000/api/v1/jobs/stats/organization \
     -H "Authorization: Bearer $TOKEN"
   ```

   Provides:
   - Active jobs / concurrency limit
   - Total jobs (24h/7d/30d)
   - Average processing time
   - Success rate percentage
   - Storage usage

**Frontend Integration**:
- `/jobs` page: Job list view with filters and pagination
- `/jobs/[id]` page: Job detail view with real-time updates
- Create Job Panel: 3-step wizard (Select → Configure → Review)
- Admin Settings: Concurrency limits and retention policies
- Status Bar: User job count + org metrics (for admins)

**Configuration**:
- `DEFAULT_JOB_CONCURRENCY_LIMIT`: Max concurrent jobs per org (default: 3)
- `DEFAULT_JOB_RETENTION_DAYS`: Days to retain jobs (default: 30)
- `JOB_CLEANUP_ENABLED`: Enable auto-cleanup (default: true)
- `JOB_CLEANUP_SCHEDULE_CRON`: Cleanup schedule (default: `0 3 * * *`)
- `JOB_CANCELLATION_TIMEOUT`: Cancellation verification timeout (default: 30s)
- `JOB_STATUS_POLL_INTERVAL`: Frontend polling interval (default: 2s)

**Best Practices**:
- Use descriptive job names for easy identification
- Set appropriate retention policies based on compliance needs
- Monitor org concurrency limits during peak usage
- Cancel stuck jobs promptly to free up capacity
- Review job logs for failed documents to identify patterns

## API Endpoints (v1)

Base URL: `http://localhost:8000/api/v1`

**Documents**:
- `POST /documents/upload` - Upload document
- `POST /documents/{id}/process` - Enqueue processing job
- `GET /documents/{id}/result` - Get processing result
- `GET /documents/{id}/content` - Get markdown content
- `GET /documents/{id}/download` - Download markdown file
- `POST /documents/batch/process` - Process multiple documents

**Jobs**:
- `POST /jobs` - Create batch job
- `GET /jobs` - List jobs (paginated, filtered by status)
- `GET /jobs/{id}` - Get job details
- `POST /jobs/{id}/start` - Start job (if not auto-started)
- `POST /jobs/{id}/cancel` - Cancel job with verification
- `DELETE /jobs/{id}` - Delete job (admin only, terminal state only)
- `GET /jobs/{id}/logs` - Get job logs (paginated)
- `GET /jobs/{id}/documents` - Get job documents with status
- `GET /jobs/stats/user` - User's job statistics
- `GET /jobs/stats/organization` - Org job stats (admin only)

**SharePoint**:
- `POST /sharepoint/inventory` - List SharePoint folder contents with metadata
- `POST /sharepoint/download` - Download selected files to batch directory

**Authentication** (when `ENABLE_AUTH=true`):
- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and receive JWT tokens
- `POST /auth/refresh` - Refresh access token
- `POST /auth/logout` - Logout (client-side token discard)
- `GET /auth/me` - Get current user profile
- `POST /auth/verify-email` - Verify email address
- `POST /auth/request-password-reset` - Request password reset
- `POST /auth/reset-password` - Reset password with token

**Organizations** (when `ENABLE_AUTH=true`):
- `GET /organizations` - List organizations (admin only)
- `POST /organizations` - Create organization (admin only)
- `GET /organizations/{id}` - Get organization details
- `PATCH /organizations/{id}` - Update organization
- `DELETE /organizations/{id}` - Delete organization (admin only)

**Users** (when `ENABLE_AUTH=true`):
- `GET /users` - List users in organization
- `GET /users/{id}` - Get user details
- `PATCH /users/{id}` - Update user
- `DELETE /users/{id}` - Delete user

**API Keys** (when `ENABLE_AUTH=true`):
- `GET /api-keys` - List API keys
- `POST /api-keys` - Create API key
- `GET /api-keys/{id}` - Get API key details
- `PATCH /api-keys/{id}` - Update API key (revoke, etc.)
- `DELETE /api-keys/{id}` - Delete API key

**Connections** (when `ENABLE_AUTH=true`):
- `GET /connections` - List connections
- `POST /connections` - Create connection (SharePoint, LLM, etc.)
- `GET /connections/{id}` - Get connection details
- `PATCH /connections/{id}` - Update connection
- `DELETE /connections/{id}` - Delete connection
- `POST /connections/{id}/test` - Test connection health

**Scheduled Tasks** (requires `org_admin` role):
- `GET /scheduled-tasks` - List all scheduled tasks
- `GET /scheduled-tasks/stats` - Get maintenance statistics
- `GET /scheduled-tasks/{id}` - Get task details
- `POST /scheduled-tasks/{id}/enable` - Enable a scheduled task
- `POST /scheduled-tasks/{id}/disable` - Disable a scheduled task
- `POST /scheduled-tasks/{id}/trigger` - Trigger task immediately
- `GET /scheduled-tasks/{id}/runs` - Get task run history

**Storage** (when `USE_OBJECT_STORAGE=true`):
- `GET /storage/health` - Storage service health check
- `POST /storage/upload/proxy` - Upload file proxied through backend (recommended)
- `GET /storage/object/download` - Download file proxied through backend (recommended)
- `POST /storage/upload/presigned` - Get presigned URL for direct upload (deprecated)
- `POST /storage/upload/confirm` - Confirm upload completed (deprecated)
- `GET /storage/download/{document_id}/presigned` - Get presigned URL for download (deprecated)
- `GET /storage/object/presigned` - Get presigned URL for any object (deprecated)

**Rendering** (Playwright):
- `POST /render` - Render URL and extract all content (HTML, markdown, links)
- `POST /render/extract` - Extract text content in specified format (markdown, text, html)
- `POST /render/links` - Extract all links from a URL (including document links)
- `GET /render/status` - Check Playwright rendering service status

**SAM.gov** (Federal Opportunities):
- `GET /sam/searches` - List SAM searches
- `POST /sam/searches` - Create search
- `GET /sam/searches/{id}` - Get search details
- `PATCH /sam/searches/{id}` - Update search
- `DELETE /sam/searches/{id}` - Archive search
- `POST /sam/searches/{id}/pull` - Trigger pull from SAM.gov
- `GET /sam/searches/{id}/stats` - Get search statistics
- `GET /sam/solicitations` - List solicitations with filters
- `GET /sam/solicitations/{id}` - Get solicitation details
- `GET /sam/solicitations/{id}/notices` - List notices/versions
- `GET /sam/solicitations/{id}/attachments` - List attachments
- `GET /sam/solicitations/{id}/summaries` - List summaries
- `POST /sam/solicitations/{id}/summarize` - Generate LLM summary
- `POST /sam/solicitations/{id}/download-attachments` - Download all attachments
- `GET /sam/notices/{id}` - Get notice details
- `POST /sam/notices/{id}/generate-changes` - Generate change summary
- `GET /sam/attachments/{id}` - Get attachment details
- `POST /sam/attachments/{id}/download` - Download attachment
- `GET /sam/summaries/{id}` - Get summary details
- `POST /sam/summaries/{id}/promote` - Promote to canonical
- `DELETE /sam/summaries/{id}` - Delete experimental summary
- `GET /sam/agencies` - List agencies

**System**:
- `GET /health` - API health check
- `GET /llm/status` - LLM connection status
- `GET /config/supported-formats` - Supported file formats
- `GET /config/defaults` - Default configuration
- `GET /system/queues` - Queue health and metrics
- `GET /system/queues/summary` - Queue summary by batch or jobs
- `GET /system/health/backend` - Backend API health check
- `GET /system/health/redis` - Redis health check
- `GET /system/health/celery` - Celery worker health check
- `GET /system/health/extraction` - Extraction service health check
- `GET /system/health/docling` - Docling service health check
- `GET /system/health/llm` - LLM connection health check
- `GET /system/health/sharepoint` - SharePoint / Microsoft Graph health check
- `GET /system/health/playwright` - Playwright rendering service health check
- `GET /system/health/storage` - Object storage (S3/MinIO) health check
- `GET /system/health/comprehensive` - Comprehensive health check for all components

**Interactive Docs**: http://localhost:8000/docs

## Code Quality Standards

All backend services follow comprehensive documentation standards (see existing service files as examples):

- Complete type hints for all parameters and return values
- Google/NumPy style docstrings with usage examples
- Comprehensive exception handling with detailed error messages
- Clear documentation of service interactions
- Performance notes and optimization guidelines

## Port Mappings

- `3000`: Frontend (Next.js)
- `8000`: Backend API (FastAPI)
- `8010`: Extraction Service
- `8011`: Playwright Rendering Service
- `6379`: Redis
- `5151`: Docling (when enabled, maps to internal 5001)
- `9000`: MinIO S3 API (when using MinIO profile)
- `9001`: MinIO Console (when using MinIO profile)

## Useful Debugging Commands

```bash
# Check what's running
docker ps

# Follow all logs
docker-compose logs -f

# Check file permissions in container
docker exec -it curatore-backend ls -la /app/files

# Check Redis keys
docker exec -it curatore-redis redis-cli keys '*'

# Inspect Celery queue
docker exec -it curatore-worker celery -A app.celery_app inspect active

# Check backend environment
docker exec -it curatore-backend env | grep -E "(FILES|OPENAI|CELERY)"
```
