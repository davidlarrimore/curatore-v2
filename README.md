# Curatore v2

**RAG-ready document processing and curation platform**

Curatore v2 is a multi-tenant document processing system that converts documents (PDF, DOCX, PPTX, TXT, Images, Web Pages) to Markdown, provides full-text search, and supports LLM-powered analysis. Built with FastAPI, Next.js, and async Celery workers.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-green)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15.5.0-blue)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://docker.com/)

---

## Features

### Document Processing
- **Multi-format Support**: PDF, DOCX, PPTX, TXT, Images with OCR, HTML/Web Pages
- **Intelligent Conversion**: MarkItDown, Tesseract OCR, Playwright for JS-rendered pages, and optional Docling
- **Automatic Extraction**: Documents are automatically converted to Markdown on upload
- **Asset Versioning**: Immutable version history with re-extraction support
- **Quality Metadata**: LLM-powered document analysis and tagging

### Hybrid Search (PostgreSQL + pgvector)
- **Full-text Search**: PostgreSQL tsvector with GIN indexes for keyword matching
- **Semantic Search**: Vector similarity using OpenAI embeddings (text-embedding-3-small)
- **Hybrid Mode**: Combines keyword and semantic scores with configurable weighting
- **Faceted Filtering**: Filter by source type and content type with live counts
- **No External Service**: Uses same PostgreSQL database (no OpenSearch needed)

### Web Scraping (Playwright)
- **JavaScript Rendering**: Full Chromium-based rendering for SPAs and dynamic sites
- **Scrape Collections**: Organize crawls by project with seed URLs
- **Document Discovery**: Automatically find and download PDFs, DOCXs linked on pages
- **Inline Extraction**: Content extracted during crawl (no separate job)
- **Hierarchical Browsing**: Tree-based navigation of scraped content
- **Record Preservation**: Promote pages to durable records that survive re-crawls

### SAM.gov Integration
- **Federal Opportunities**: Search and track SAM.gov contract opportunities
- **Solicitation Tracking**: Monitor solicitations and amendments over time
- **Attachment Processing**: Download and extract attachments automatically
- **AI Summaries**: LLM-powered analysis with compliance checklists
- **Rate Limit Management**: Automatic tracking of 1,000 calls/day limit

### Multi-Tenant Architecture
- **Organizations**: Complete tenant isolation with separate storage
- **User Management**: Role-based access control (Admin, Member, Viewer)
- **API Keys**: Headless authentication for automation
- **Connection Management**: Runtime-configurable service connections
- **Scheduled Tasks**: Database-backed maintenance with admin controls

### Object Storage (S3/MinIO)
- **S3-Compatible**: Works with MinIO (dev) or AWS S3 (production)
- **Human-Readable Paths**: Organized by source type (uploads, scrape, sharepoint, sam)
- **Artifact Tracking**: All files tracked in database with provenance
- **Lifecycle Policies**: Automatic retention and cleanup via S3 policies

### Integrations
- **SharePoint**: Microsoft Graph API integration for document retrieval
- **LLM Providers**: OpenAI, Ollama, OpenWebUI, LM Studio support
- **OpenAI Embeddings**: Semantic search via text-embedding-3-small
- **Custom Endpoints**: Extensible connection system for any service

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ (for local frontend development)
- Python 3.12+ (for local backend development)

### Start All Services

```bash
# Start all services (backend, worker, frontend, redis, extraction, minio, postgres)
./scripts/dev-up.sh

# Or using Make
make up
```

### Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **MinIO Console**: http://localhost:9001 (minioadmin/minioadmin)

### Initial Setup

```bash
# Initialize storage buckets
./scripts/init_storage.sh

# Create admin user and seed data
docker exec curatore-backend python -m app.commands.seed --create-admin
```

See [ADMIN_SETUP.md](./ADMIN_SETUP.md) for default admin credentials and initial configuration.

---

## Tech Stack

### Backend
- **FastAPI**: High-performance async Python API
- **SQLAlchemy**: Async ORM with SQLite/PostgreSQL support
- **Celery**: Distributed task queue with Redis broker
- **Celery Beat**: Scheduled task execution
- **Alembic**: Database migrations
- **Pydantic**: Data validation and settings management

### Frontend
- **Next.js 15**: React framework with App Router
- **TypeScript**: Type-safe frontend development
- **Tailwind CSS**: Utility-first styling with dark mode
- **React 19**: Latest React features

### Services
- **PostgreSQL + pgvector**: Database with vector search extension
- **Redis**: Message broker and distributed locking
- **MinIO/S3**: Object storage for all files
- **Extraction Service**: Standalone document conversion service
- **Playwright Service**: Browser-based web rendering
- **Docling** (optional): Advanced document converter

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend    │────▶│    Redis    │
│  (Next.js)  │     │  (FastAPI)   │     │  (Broker)   │
└─────────────┘     └──────────────┘     └─────────────┘
                            │                     │
                    ┌───────┴───────┐             ▼
                    │               │     ┌──────────────┐
                    ▼               ▼     │    Worker    │
            ┌──────────────┐ ┌──────────┐ │   (Celery)   │
            │   MinIO/S3   │ │PostgreSQL│ └──────────────┘
            │   Storage    │ │+ pgvector│         │
            └──────────────┘ └──────────┘         │
                                          ┌───────┴───────┐
                                          │               │
                                          ▼               ▼
                                  ┌──────────────┐ ┌──────────────┐
                                  │  Extraction  │ │  Playwright  │
                                  │   Service    │ │   Service    │
                                  └──────────────┘ └──────────────┘
```

### Storage Structure (Object Storage)

```
curatore-uploads/                    # Raw/source files
└── {org_id}/
    ├── uploads/{asset_uuid}/        # File uploads
    ├── scrape/{collection}/         # Web scraping
    │   ├── pages/                   # Scraped web pages
    │   └── documents/               # Downloaded documents
    ├── sharepoint/{site}/           # SharePoint files
    └── sam/solicitations/           # SAM.gov attachments

curatore-processed/                  # Extracted markdown
└── {org_id}/
    └── ...                          # Mirrors uploads structure

curatore-temp/                       # Temporary processing files
```

---

## Development

### Backend Development

```bash
# Run tests
pytest backend/tests -v

# Run with coverage
pytest backend/tests --cov=backend/app

# Start backend locally (with hot reload)
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Development

```bash
# Install dependencies
cd frontend
npm install

# Start dev server
npm run dev

# Type checking
npm run type-check

# Linting
npm run lint
```

### Worker Development

```bash
# View worker logs
./scripts/tail_worker.sh

# Worker auto-restarts on code changes via watchmedo
```

---

## Testing

```bash
# Run all tests
./scripts/run_all_tests.sh

# Backend tests only
pytest backend/tests

# API smoke tests
./scripts/api_smoke_test.sh

# Queue health check
./scripts/queue_health.sh
```

---

## Configuration

Curatore v2 supports two configuration methods:

1. **YAML Configuration** (recommended): `config.yml` at project root
2. **Environment Variables** (legacy): `.env` file

**Configuration Priority**: config.yml → environment variables → built-in defaults

### Quick Start

```bash
# Copy example configuration
cp config.yml.example config.yml
cp .env.example .env

# Edit config.yml with your credentials
# Use ${VAR_NAME} to reference secrets from .env

# Validate configuration
python -m app.commands.validate_config

# Start services
docker-compose up -d
```

### Key Environment Variables

See `.env.example` for complete list. Key variables:

#### LLM Configuration
- `OPENAI_API_KEY`: API key for LLM provider
- `OPENAI_MODEL`: Model name (default: `gpt-4o-mini`)
- `OPENAI_BASE_URL`: API endpoint (supports Ollama, OpenWebUI, etc.)

#### Object Storage (Required)
- `MINIO_ENDPOINT`: MinIO/S3 endpoint (default: `minio:9000`)
- `MINIO_ACCESS_KEY`: Access key (default: `minioadmin`)
- `MINIO_SECRET_KEY`: Secret key (default: `minioadmin`)

#### Search (PostgreSQL + pgvector)
- `SEARCH_ENABLED`: Enable hybrid search (default: `true`)
- Embedding model configured in `config.yml` under `llm.models.embedding`

#### SAM.gov (Optional)
- `SAM_API_KEY`: API key from api.sam.gov
- `SAM_ENABLED`: Enable SAM.gov integration (default: `false`)

#### Authentication
- `ENABLE_AUTH`: Enable multi-tenant authentication (default: `true`)
- `JWT_SECRET_KEY`: Secret for JWT token signing

See **[docs/CONFIGURATION.md](./docs/CONFIGURATION.md)** for complete reference.

---

## API Endpoints

Base URL: `http://localhost:8000/api/v1`

### Assets
- `GET /assets` - List assets with filters
- `GET /assets/{id}` - Get asset details
- `POST /assets/{id}/reextract` - Re-run extraction
- `GET /assets/{id}/versions` - Get version history
- `GET /assets/health` - Collection health metrics
- `POST /assets/bulk-upload/preview` - Preview bulk upload changes
- `POST /assets/bulk-upload/apply` - Apply bulk upload

### Runs
- `GET /runs` - List runs with filters
- `GET /runs/{id}` - Get run details
- `GET /runs/{id}/logs` - Get run logs
- `POST /runs/{id}/retry` - Retry failed run

### Search
- `POST /search` - Full-text search with facets
- `GET /search` - Simple search via query params
- `GET /search/stats` - Index statistics
- `POST /search/reindex` - Trigger reindex (admin)
- `GET /search/health` - Search service health

### Web Scraping
- `GET /scrape/collections` - List collections
- `POST /scrape/collections` - Create collection
- `POST /scrape/collections/{id}/crawl` - Start crawl
- `GET /scrape/collections/{id}/assets` - List scraped assets
- `GET /scrape/collections/{id}/tree` - Hierarchical tree

### SAM.gov
- `GET /sam/searches` - List SAM searches
- `POST /sam/searches` - Create search
- `POST /sam/searches/{id}/pull` - Pull from SAM.gov
- `GET /sam/solicitations` - List solicitations
- `GET /sam/notices` - List notices
- `GET /sam/usage` - API usage tracking

### Storage
- `GET /storage/health` - Storage health check
- `POST /storage/upload/proxy` - Upload file (proxied)
- `GET /storage/object/download` - Download file (proxied)

### Authentication
- `POST /auth/login` - Login with credentials
- `POST /auth/refresh` - Refresh access token
- `GET /auth/me` - Get current user

### Scheduled Tasks (Admin)
- `GET /scheduled-tasks` - List scheduled tasks
- `POST /scheduled-tasks/{id}/trigger` - Trigger task manually
- `POST /scheduled-tasks/{id}/enable` - Enable task
- `POST /scheduled-tasks/{id}/disable` - Disable task

**Interactive Documentation**: http://localhost:8000/docs

---

## Documentation

- **[ADMIN_SETUP.md](./ADMIN_SETUP.md)** - Initial setup and admin credentials
- **[docs/CONFIGURATION.md](./docs/CONFIGURATION.md)** - YAML configuration guide
- **[docs/API_DOCUMENTATION.md](./docs/API_DOCUMENTATION.md)** - Complete API reference
- **[USER_GUIDE.md](./USER_GUIDE.md)** - End-user documentation
- **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** - Production deployment guide
- **[CLAUDE.md](./CLAUDE.md)** - Development patterns and conventions

---

## Common Tasks

### Create Admin User

```bash
docker exec curatore-backend python -m app.commands.seed --create-admin
```

### Initialize Storage

```bash
./scripts/init_storage.sh
```

### Check System Health

```bash
curl http://localhost:8000/api/v1/system/health/comprehensive | jq '.'
```

### Trigger Search Reindex

```bash
curl -X POST http://localhost:8000/api/v1/search/reindex \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### View Logs

```bash
# All services
./scripts/dev-logs.sh

# Specific service
./scripts/dev-logs.sh backend
./scripts/dev-logs.sh worker
```

### Clean Up

```bash
# Stop services
./scripts/dev-down.sh

# Remove containers and volumes
./scripts/clean.sh
```

---

## Port Mappings

| Port | Service |
|------|---------|
| 3000 | Frontend (Next.js) |
| 5432 | PostgreSQL + pgvector |
| 8000 | Backend API (FastAPI) |
| 8010 | Extraction Service |
| 8011 | Playwright Service |
| 6379 | Redis |
| 9000 | MinIO S3 API |
| 9001 | MinIO Console |
| 5151 | Docling (when enabled) |

---

## Development Backlog

Planned features and improvements:

### Archive & OneNote Extraction
- **ZIP Archive Support**: Extract and process files from `.zip` archives
  - Recursive extraction of nested archives
  - File type detection and routing to appropriate extractors
  - Maintain folder structure metadata
- **OneNote Support**: Extract content from `.one` files
  - Microsoft OneNote notebook parsing
  - Section and page hierarchy preservation
  - Embedded image and attachment handling

---

## Security

- Change default admin password immediately after first login
- Use strong passwords in production
- Store credentials in secrets manager (not .env files)
- Enable SSL/TLS in production
- Review security settings in DEPLOYMENT_GUIDE.md

---

## Support & Contributing

For issues, questions, or contributions, please contact the development team or open an issue in the repository.

## License

[Add your license here]
