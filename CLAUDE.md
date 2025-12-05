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
  - Delegates to extraction service or Docling based on `CONTENT_EXTRACTOR` setting
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

### API Structure

All API endpoints are versioned under `/api/v1/`:

```
backend/app/
├── api/
│   └── v1/
│       ├── routers/
│       │   ├── documents.py    # Document upload, process, download
│       │   ├── jobs.py         # Job status, polling
│       │   └── system.py       # Health, config, queue info
│       └── models.py           # V1-specific Pydantic models
├── models.py                   # Shared domain models
└── services/                   # Business logic layer
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

Curatore supports multiple extraction engines via the `CONTENT_EXTRACTOR` environment variable:

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

### File Storage

All file operations use volume-mounted storage at `/app/files` (in containers):

```
/app/files/
├── uploaded_files/       # User uploads (original files)
├── processed_files/      # Converted markdown output
└── batch_files/          # Operator-provided bulk inputs
```

**Important**: File paths in code should use `settings.upload_dir`, `settings.processed_dir`, etc. from `config.py`. Never hardcode paths.

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
4. Update frontend API client if needed (`frontend/lib/api.ts`)

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
- `CONTENT_EXTRACTOR`: `default` | `docling` | `none`
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

## Common Development Tasks

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

**System**:
- `GET /health` - API health check
- `GET /llm/status` - LLM connection status
- `GET /config/supported-formats` - Supported file formats
- `GET /config/defaults` - Default configuration
- `GET /system/queues` - Queue health and metrics
- `GET /system/queues/summary` - Queue summary by batch or jobs

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
