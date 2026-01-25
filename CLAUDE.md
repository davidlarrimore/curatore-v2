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

Curatore supports multiple extraction engines selected per job:

- **`extraction-service`**: Uses the internal extraction-service microservice (recommended)
- **`docling`**: Uses Docling Serve for rich PDFs and Office documents

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

#### Object Storage (S3/MinIO) - REQUIRED

**Curatore v2 now requires object storage** - filesystem storage has been removed. All files are stored in S3-compatible object storage (MinIO for development, AWS S3 for production).

**BREAKING CHANGE (v2.3+):** Local filesystem storage has been completely removed. The `/app/files` directory is no longer used.

**Architecture:**
```
Frontend → Backend API → MinIO/S3
                ↓
         presigned URLs for direct upload/download
```

**Object Storage Structure:**
```
MinIO/S3 Buckets:
├── curatore-uploads/           # Uploaded source files
│   └── {org_id}/
│       └── {document_id}/
│           └── uploaded/
│               └── {filename}
├── curatore-processed/         # Processed markdown files
│   └── {org_id}/
│       └── {document_id}/
│           └── processed/
│               └── {filename}.md
└── curatore-temp/              # Temporary processing files
    └── {job_id}/
        └── {temp_files}
```

**Key Features:**
- **Provider-agnostic**: Works with MinIO (development) or AWS S3 (production)
- **Presigned URLs**: Frontend uploads/downloads directly to storage, bypassing backend for large files
- **Artifact tracking**: Database tracks all stored files via the `Artifact` model
- **S3 lifecycle policies**: Automatic file expiration and retention (no Celery cleanup tasks needed)
- **Multi-bucket setup**: Separate buckets for uploads, processed files, and temp files
- **Multi-tenant isolation**: Organization ID prefixes ensure tenant isolation
- **Integrated MinIO SDK**: Direct connection from backend (no separate microservice needed)

**Setup (Development):**
1. MinIO starts automatically with backend services (no profile needed)
2. Run `./scripts/init_storage.sh` to create buckets and set lifecycle policies
3. Add `127.0.0.1 minio` to `/etc/hosts` for presigned URL access from browser

**Configuration:**
- `USE_OBJECT_STORAGE`: Must be `true` (default: true, no filesystem fallback)
- `MINIO_ENDPOINT`: MinIO server endpoint (default: minio:9000)
- `MINIO_PUBLIC_ENDPOINT`: Public endpoint for presigned URLs (must be reachable from clients)
- `MINIO_ACCESS_KEY`: MinIO access key (default: minioadmin)
- `MINIO_SECRET_KEY`: MinIO secret key (default: minioadmin)
- `MINIO_BUCKET_UPLOADS`: Bucket for uploaded files
- `MINIO_BUCKET_PROCESSED`: Bucket for processed files
- `MINIO_BUCKET_TEMP`: Bucket for temporary files
- See `.env.example` for complete configuration options

**File Upload/Download Workflow:**
1. **Upload**: Frontend requests presigned upload URL from `POST /api/v1/storage/upload/presigned`
2. **Direct Upload**: Frontend uploads file directly to MinIO using presigned URL
3. **Confirm**: Frontend confirms upload via `POST /api/v1/storage/upload/confirm`
4. **Artifact**: Backend creates artifact record in database for tracking
5. **Process**: Celery task downloads from MinIO, processes, uploads result back to MinIO
6. **Download**: Frontend requests presigned download URL from `GET /api/v1/storage/download/{document_id}/presigned`
7. **Direct Download**: Frontend downloads directly from MinIO using presigned URL

**Key Files:**
- `backend/app/services/minio_service.py`: MinIO SDK integration
- `backend/app/services/artifact_service.py`: Database tracking for stored files
- `backend/app/api/v1/routers/storage.py`: Presigned URL endpoints
- `backend/app/commands/init_storage.py`: Bucket initialization command
- `scripts/init_storage.sh`: Storage initialization script

**API Endpoints:**
- `GET /api/v1/storage/health`: Check object storage status
- `POST /api/v1/storage/upload/presigned`: Get presigned URL for upload
- `POST /api/v1/storage/upload/confirm`: Confirm upload completed
- `GET /api/v1/storage/download/{document_id}/presigned`: Get presigned URL for download

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
- [ ] `/settings` (User Settings)
- [ ] `/settings-admin` (Admin Settings)
- [ ] `/users` (User Management)
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

**Storage** (when `USE_OBJECT_STORAGE=true`):
- `GET /storage/health` - Storage service health check
- `POST /storage/upload/presigned` - Get presigned URL for direct upload
- `POST /storage/upload/confirm` - Confirm upload completed
- `GET /storage/download/{document_id}/presigned` - Get presigned URL for download

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
