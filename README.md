# Curatore v2

**RAG-ready document processing and optimization platform**

Curatore v2 is a multi-tenant document processing system that converts documents (PDF, DOCX, PPTX, TXT, Images) to Markdown, evaluates quality with an LLM, and optimizes structure for vector databases. Built with FastAPI, Next.js, and async Celery workers.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-green)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15.5.0-blue)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://docker.com/)

---

## Features

### Document Processing
- **Multi-format Support**: PDF, DOCX, PPTX, TXT, Images with OCR
- **Intelligent Conversion**: MarkItDown and Tesseract OCR with Docling fallback
- **Quality Assessment**: LLM-powered document evaluation and scoring
- **Vector Optimization**: Structure optimization for RAG applications
- **Batch Processing**: Process multiple documents asynchronously

### Multi-Tenant Architecture
- **Organizations**: Complete tenant isolation with separate storage
- **User Management**: Role-based access control (Admin, Member, Viewer)
- **API Keys**: Headless authentication for automation
- **Connection Management**: Runtime-configurable service connections
- **Settings**: Organization and user-level configuration with deep merge

### Storage Management
- **Hierarchical Organization**: Organized by organization and batch
- **File Deduplication**: SHA-256 content-based duplicate detection (30-70% savings)
- **Automatic Retention**: Configurable cleanup policies with TTL
- **Storage Analytics**: Real-time usage statistics and savings metrics

### Integrations
- **SharePoint**: Microsoft Graph API integration for document retrieval
- **LLM Providers**: OpenAI, Ollama, OpenWebUI, LM Studio support
- **Custom Endpoints**: Extensible connection system for any service

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ (for local frontend development)
- Python 3.12+ (for local backend development)

### Start All Services

```bash
# Start all services (backend, worker, frontend, redis, extraction)
./scripts/dev-up.sh

# Or using Make
make up
```

### Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

### Initial Setup

See [ADMIN_SETUP.md](./ADMIN_SETUP.md) for default admin credentials and initial configuration.

---

## Tech Stack

### Backend
- **FastAPI**: High-performance async Python API
- **SQLAlchemy**: Async ORM with SQLite/PostgreSQL support
- **Celery**: Distributed task queue with Redis broker
- **Alembic**: Database migrations
- **Pydantic**: Data validation and settings management

### Frontend
- **Next.js 15**: React framework with App Router
- **TypeScript**: Type-safe frontend development
- **Tailwind CSS**: Utility-first styling with dark mode
- **React 19**: Latest React features

### Services
- **Redis**: Message broker and caching
- **Extraction Service**: Standalone FastAPI service for document conversion
- **Docling** (optional): Advanced document converter

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

# Extraction service tests
pytest extraction-service/tests -v

# API smoke tests
./scripts/api_smoke_test.sh

# Queue health check
./scripts/queue_health.sh
```

---

## Configuration

Key configuration options (see `.env.example` for complete list):

### LLM Configuration
- `OPENAI_API_KEY`: API key for LLM provider
- `OPENAI_MODEL`: Model name (default: `gpt-4o-mini`)
- `OPENAI_BASE_URL`: API endpoint (supports Ollama, OpenWebUI, etc.)

### Extraction
- `EXTRACTION_PRIORITY`: `default` | `docling` | `none`
- `EXTRACTION_SERVICE_URL`: Extraction service endpoint
- `DOCLING_SERVICE_URL`: Docling service endpoint (when enabled)

### Authentication
- `ENABLE_AUTH`: Enable multi-tenant authentication (default: `true`)
- `JWT_SECRET_KEY`: Secret for JWT token signing
- `ADMIN_EMAIL`: Initial admin user email
- `ADMIN_PASSWORD`: Initial admin password

### Storage
- `FILE_DEDUPLICATION_ENABLED`: Enable file deduplication (default: `true`)
- `FILE_RETENTION_UPLOADED_DAYS`: Retention for uploaded files (default: 7)
- `FILE_RETENTION_PROCESSED_DAYS`: Retention for processed files (default: 30)
- `FILE_CLEANUP_ENABLED`: Enable automatic cleanup (default: `true`)

### SharePoint
- `MS_TENANT_ID`: Azure AD tenant ID
- `MS_CLIENT_ID`: Azure AD app client ID
- `MS_CLIENT_SECRET`: Azure AD app client secret

---

## Architecture

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

### Storage Structure

```
/app/files/
├── organizations/{org_id}/
│   ├── batches/{batch_id}/
│   │   ├── uploaded/
│   │   ├── processed/
│   │   └── metadata.json
│   └── adhoc/
├── shared/              # Unauthenticated mode
├── dedupe/              # Content-addressable storage
│   └── {hash[:2]}/{hash}/
│       ├── content.ext
│       └── refs.json
└── temp/                # Temporary processing files
```

---

## API Endpoints

Base URL: `http://localhost:8000/api/v1`

### Documents
- `POST /documents/upload` - Upload document
- `POST /documents/{id}/process` - Process document
- `GET /documents/{id}/result` - Get result
- `GET /documents/{id}/content` - Get markdown
- `POST /documents/batch/process` - Batch processing

### Storage
- `GET /storage/stats` - Storage usage statistics
- `POST /storage/cleanup` - Trigger cleanup
- `GET /storage/retention` - Retention policy
- `GET /storage/deduplication` - Deduplication stats
- `GET /storage/duplicates` - List duplicate files

### SharePoint
- `POST /sharepoint/inventory` - List folder contents
- `POST /sharepoint/download` - Download files

### Authentication
- `POST /auth/login` - Login with credentials
- `POST /auth/refresh` - Refresh access token
- `GET /auth/me` - Get current user

### Organizations & Users
- `GET /organizations` - List organizations
- `GET /users` - List users
- `POST /users/invite` - Invite user

### Connections
- `GET /connections` - List connections
- `POST /connections` - Create connection
- `POST /connections/{id}/test` - Test connection

**Interactive Documentation**: http://localhost:8000/docs

---

## Documentation

- **[ADMIN_SETUP.md](./ADMIN_SETUP.md)** - Initial setup and admin credentials
- **[API_DOCUMENTATION.md](./API_DOCUMENTATION.md)** - Complete API reference
- **[USER_GUIDE.md](./USER_GUIDE.md)** - End-user documentation
- **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** - Production deployment guide
- **[CLAUDE.md](./CLAUDE.md)** - Development patterns and conventions

---

## Common Tasks

### Create Admin User

```bash
docker exec curatore-backend python -m app.commands.seed --create-admin
```

### Check System Health

```bash
curl http://localhost:8000/api/v1/system/health/comprehensive | jq '.'
```

### Monitor Queue

```bash
./scripts/queue_health.sh
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

- `3000` - Frontend (Next.js)
- `8000` - Backend API (FastAPI)
- `8010` - Extraction Service
- `6379` - Redis
- `5151` - Docling (when enabled)

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
