# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Curatore v2 is a RAG-ready document processing and optimization platform. It converts documents (PDF, DOCX, PPTX, TXT, Images) to Markdown, evaluates quality with an LLM, and optionally optimizes structure for vector databases. The application consists of:

- **Backend**: FastAPI (Python 3.12+) with async Celery workers
- **Frontend**: Next.js 15.5 (TypeScript, React 19) with Tailwind CSS
- **Extraction Service**: Separate microservice for document conversion
- **Queue System**: Redis + Celery for async job processing
- **Optional Docling**: External document converter for rich PDFs/Office docs

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
                    ┌──────────────┐     ┌──────────────┐
                    │  Extraction  │     │   Storage    │
                    │   Service    │     │  (/app/files)│
                    └──────────────┘     └──────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   Docling    │
                    │  (Optional)  │
                    └──────────────┘
```

### Backend Service Layer

The backend follows a service-oriented architecture with clear separation of concerns:

- **`document_service.py`**: Core document processing pipeline
  - Multi-format conversion with intelligent fallback strategies
  - OCR integration for image-based content extraction
  - Delegates to extraction service or Docling based on `EXTRACTION_PRIORITY` setting
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
  - Automatic fallback on failures

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
│       │   └── connections.py     # Runtime connection management
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

### Extraction Engines

Curatore supports multiple extraction engines via the `EXTRACTION_PRIORITY` environment variable:

- **`default`**: Uses the internal extraction-service microservice (recommended)
- **`docling`**: Uses Docling Serve for rich PDFs and Office documents
- **`none`**: Disables external extraction (fallback only)

**Extraction Service** (`extraction-service/`):
- Standalone FastAPI microservice on port 8010
- Handles PDF, DOCX, PPTX, TXT, Images with OCR
- Uses MarkItDown and Tesseract for conversions
- Endpoint: `POST /api/v1/extract`

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

#### Hierarchical Storage Structure (v2.1+)

Curatore uses a hierarchical file organization system with multi-tenant isolation, batch groupings, and automatic deduplication:

```
/app/files/
├── organizations/                  # Multi-tenant file isolation
│   └── {organization_id}/          # UUID-based organization folder
│       ├── batches/
│       │   └── {batch_id}/         # Batch-grouped files
│       │       ├── uploaded/       # Original uploaded files (or symlinks)
│       │       │   └── {document_id}_{name}.ext
│       │       ├── processed/      # Converted markdown files
│       │       │   └── {document_id}_{name}.md
│       │       └── metadata.json   # Batch metadata + expiration
│       └── adhoc/                  # Single-file uploads (no batch)
│           ├── uploaded/
│           └── processed/
├── shared/                         # For unauthenticated mode (ENABLE_AUTH=false)
│   ├── batches/{batch_id}/...
│   └── adhoc/...
├── dedupe/                         # Content-addressable storage (deduplication)
│   └── {hash[:2]}/                 # Shard by first 2 chars of SHA-256
│       └── {hash}/                 # Full hash directory
│           ├── content.ext         # Actual file content (stored once)
│           └── refs.json           # Reference count + document IDs
├── temp/                           # Temporary processing files
│   └── {job_id}/                   # Auto-cleanup after job completion
├── uploaded_files/                 # Legacy flat structure (backward compat)
├── processed_files/                # Legacy flat structure (backward compat)
└── batch_files/                    # Legacy bulk inputs (backward compat)
```

**File Deduplication:**
- Identical files are stored only once in `dedupe/` using SHA-256 content hashing
- Original file locations contain symlinks (default) or copies to deduplicated content
- Reference counting tracks how many documents use each unique file
- Storage savings are reported via `/api/v1/storage/deduplication` endpoint

**Automatic Cleanup:**
- Expired files are automatically deleted based on configurable retention periods:
  - Uploaded files: 7 days (configurable via `FILE_RETENTION_UPLOADED_DAYS`)
  - Processed files: 30 days (configurable via `FILE_RETENTION_PROCESSED_DAYS`)
  - Batch files: 14 days (configurable via `FILE_RETENTION_BATCH_DAYS`)
  - Temp files: 24 hours (configurable via `FILE_RETENTION_TEMP_HOURS`)
- Cleanup runs daily at 2 AM UTC (configurable via `FILE_CLEANUP_SCHEDULE_CRON`)
- Active jobs are protected from cleanup
- Deduplicated files are only deleted when all references are removed

**Database Storage** (when using SQLite):
```
/app/data/
└── curatore.db          # SQLite database file
```

**Important**:
- File paths in code should use `path_service.get_document_path()` or `settings.upload_dir`, `settings.processed_dir`, etc. from `config.py`. Never hardcode paths.
- Both `files/` and `data/` directories are bind-mounted from the host in docker-compose
- SQLite database file persists across container restarts via volume mount
- Set `USE_HIERARCHICAL_STORAGE=true` to enable new structure (default: true)
- Legacy flat structure is maintained for backward compatibility

**Configuration:**
- Hierarchical storage: `USE_HIERARCHICAL_STORAGE` (default: true)
- Deduplication: `FILE_DEDUPLICATION_ENABLED` (default: true)
- Deduplication strategy: `FILE_DEDUPLICATION_STRATEGY` (symlink | copy | reference)
- Automatic cleanup: `FILE_CLEANUP_ENABLED` (default: true)
- See `.env.example` for complete configuration options

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

## Development Patterns

### Making Changes to the Processing Pipeline

1. **Document Service** (`backend/app/services/document_service.py`):
   - Core processing logic for document conversion
   - Uses extraction service for actual conversion
   - Handles quality assessment and optimization

2. **Extraction Service** (`extraction-service/app/services/extraction_service.py`):
   - Low-level conversion using MarkItDown and Tesseract
   - Maintains fallback chains for different file types

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
- `openai`: OpenAI API connection (or compatible endpoints)
- `smtp`: SMTP email server connection
- Custom types can be added by extending the Connection model

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
- `EXTRACTION_PRIORITY`: `default` | `docling` | `none`
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
- `GET /jobs/{job_id}` - Get job status
- `GET /jobs/by-document/{document_id}` - Get last job for document

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
- `6379`: Redis
- `5151`: Docling (when enabled, maps to internal 5001)

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
