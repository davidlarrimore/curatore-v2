# Curatore 🚀

RAG‑ready document processing and optimization platform.

Curatore converts documents to Markdown, evaluates quality with an LLM, and optionally optimizes structure for vector databases. It ships as a FastAPI backend and a Next.js frontend with a single, stable API at `/api/v1`.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-green)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15.5.0-blue)](https://nextjs.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://docker.com/)

---

## ✨ **Features**

### **🔄 Document Processing Pipeline**
- **Universal Format Support**: PDF, DOCX, PPTX, TXT, Images (PNG, JPG, etc.)
- **Advanced OCR**: Tesseract-powered image text extraction with configurable languages
- **Intelligent Conversion**: Multi-stage fallback system with format-specific optimization
- **Quality Assessment**: Comprehensive scoring using conversion metrics and LLM evaluation

### **🤖 LLM-Powered Quality Analysis**
- **Multi-Metric Evaluation**: Clarity, completeness, relevance, and markdown quality (1-10 scale)
- **Flexible LLM Support**: OpenAI API, Ollama, OpenWebUI, LM Studio, and other OpenAI-compatible endpoints
- **Vector Optimization**: RAG-specific content restructuring and chunk boundary optimization
- **Quality Thresholds**: Configurable scoring thresholds for production readiness

### **📊 Advanced Export & Download System**
- **Individual Downloads**: Single processed markdown files
- **Smart ZIP Archives**: 
  - Combined exports with merged documents and processing summaries
  - RAG-ready filtered collections meeting quality thresholds
  - Custom bulk selections with metadata
- **Processing Reports**: Detailed statistics, quality analysis, and optimization status

### **🎯 RAG Optimization Features**
- **Content Restructuring**: Automatic header hierarchy adjustment for seamless merging
- **Quality Indicators**: Visual status tracking (✅ RAG Ready, ⚠️ Needs Improvement, 🎯 Vector Optimized)
- **Batch Processing**: Efficient multi-document processing with progress tracking
- **Threshold Management**: Customizable quality gates for production deployment

---

## 🏗️ **Architecture**

### **Backend Services (FastAPI)**
- **`document_service.py`** - Core document processing pipeline
  - Multi-format conversion with intelligent fallback strategies
  - OCR integration for image-based content extraction
  - Content quality assessment and scoring algorithms
  - File management with UUID-based organization

- **`llm_service.py`** - LLM integration and evaluation
  - Flexible endpoint configuration (OpenAI, local models, custom APIs)
  - Multi-criteria document evaluation with detailed scoring
  - Vector optimization prompt engineering
  - Connection monitoring and error handling

- **`storage_service.py`** - In-memory storage management
  - Processing result caching with efficient retrieval
  - Batch operation state management
  - CRUD operations for individual and batch results
  - Automatic cross-referencing between batch and individual results

- **`zip_service.py`** - Archive creation and export
  - Individual document archives with processing summaries
  - Combined exports with merged documents
  - RAG-ready filtering with quality threshold application
  - Temporary file management with automatic cleanup

### **Frontend (Next.js + TypeScript)**
- **Modern React Interface**: Drag-and-drop file uploads, real-time processing tracking
- **Quality Dashboard**: Live scoring updates, threshold visualization, export management
- **Responsive Design**: Tailwind CSS with mobile-optimized layouts
- **Type Safety**: Full TypeScript integration with comprehensive type definitions

### **API Structure**
```
backend/app/
├── services/
│   ├── document_service.py      # Processing pipeline
│   ├── llm_service.py           # LLM integration and evaluation
│   ├── storage_service.py       # In‑memory result store
│   └── zip_service.py           # Archive creation/export
├── api/
│   └── v1/
│       └── routers/
│           ├── documents.py     # Documents + processing
│           ├── jobs.py          # Job status
│           └── system.py        # Health/config/queues
├── models.py                    # Pydantic models
├── config.py                    # Settings
└── main.py                      # FastAPI app (mounts /api/v1 and legacy /api)
```

Use explicit versioned paths like `/api/v1/*`. The legacy alias `/api/*` maps to v1 and returns deprecation headers.

---

## 🚀 **Quick Start**

### **Prerequisites**

- **Docker Desktop** (recommended) - [Download](https://www.docker.com/products/docker-desktop)
- **OR Manual Setup**: Node.js 18+ and Python 3.12+

### **🐳 Using Docker (Recommended)**

1. **Clone and Setup**:
   ```bash
   git clone <repository-url>
   cd curatore
   cp .env.example .env
   # Edit .env with your configuration (see Configuration section)
   ```

2. **Start the Application**:
   ```bash
   ./scripts/dev-up.sh
   ```

3. **Access the Applications**:
   - **Frontend**: http://localhost:3000
   - **Backend API**: http://localhost:8000
   - **API Docs (all)**: http://localhost:8000/docs
   - **API Docs**: http://localhost:8000/api/v1/docs
   - **Health Check**: http://localhost:8000/api/v1/health

### **⚙️ Manual Installation**

#### **Backend Setup**
```bash
cd backend
pip install -r requirements.txt
# Install Tesseract OCR (see Tesseract Installation section)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### **Frontend Setup**
```bash
cd frontend
npm install
npm run dev
```

#### **Tesseract OCR Installation**
- **Ubuntu/Debian**: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
- **macOS**: `brew install tesseract`
- **Windows**: Download from [GitHub releases](https://github.com/UB-Mannheim/tesseract/wiki)

---

## ⚙️ **Configuration**

### **Environment Variables**

Create a `.env` file in the project root with the following configuration:

```bash
# ============================================================================
# LLM CONFIGURATION
# ============================================================================

# OpenAI API Configuration (required for LLM features)
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_VERIFY_SSL=true
OPENAI_TIMEOUT=60
OPENAI_MAX_RETRIES=3

# ============================================================================
# OCR CONFIGURATION
# ============================================================================

# Tesseract OCR settings
OCR_LANG=eng                    # Language: eng, spa, fra, deu, chi_sim, etc.
OCR_PSM=3                       # Page Segmentation Mode (1-13)

# ============================================================================
# FILE STORAGE CONFIGURATION
# ============================================================================

# File directories (Docker paths)
FILES_ROOT=/app/files
UPLOAD_DIR=/app/files/uploaded_files
PROCESSED_DIR=/app/files/processed_files
BATCH_DIR=/app/files/batch_files

# File size limits
MAX_FILE_SIZE=52428800          # 50MB in bytes

# ============================================================================
# QUALITY THRESHOLDS
# ============================================================================

# Conversion quality (0-100 scale)
DEFAULT_CONVERSION_THRESHOLD=70

# LLM evaluation thresholds (1-10 scale)
DEFAULT_CLARITY_THRESHOLD=7
DEFAULT_COMPLETENESS_THRESHOLD=7
DEFAULT_RELEVANCE_THRESHOLD=7
DEFAULT_MARKDOWN_THRESHOLD=7

# ============================================================================
# API CONFIGURATION
# ============================================================================

# FastAPI settings
API_TITLE="Curatore API"
API_VERSION="2.0.0"
DEBUG=true

# CORS settings for frontend integration
CORS_ORIGINS=["http://localhost:3000"]
CORS_CREDENTIALS=true
CORS_METHODS=["*"]
CORS_HEADERS=["*"]
```

### **Docling Extraction Engine**

Curatore supports two extraction engines:

- Default extraction-service (internal microservice)
- Docling Serve (external image/document converter) — recommended for rich PDFs and Office docs

Set the extractor priority via `EXTRACTION_PRIORITY`:

```bash
# Use the default internal extraction-service
EXTRACTION_PRIORITY=default

# Or enable Docling
EXTRACTION_PRIORITY=docling

# Docling connection
DOCLING_SERVICE_URL=http://docling:5001
DOCLING_TIMEOUT=60
DOCLING_VERIFY_SSL=true
```

If `EXTRACTION_PRIORITY` is not set, Curatore defaults to the internal extraction-service (equivalent to `EXTRACTION_PRIORITY=default`).

To control whether the bundled `docling` service starts, set the boolean in your `.env`:

```bash
ENABLE_DOCLING_SERVICE=true   # or false
```

Use the Makefile helper to respect this toggle:

```bash
make up
```

Notes:
- The Docling port mapping is baked into `docker-compose.yml` as `5151:5001`.
- The Docling image and tag are baked into `docker-compose.yml` (`ghcr.io/docling-project/docling-serve-cpu:latest`). The Docling container name is baked in as `curatore-docling`.

Behavior when `EXTRACTION_PRIORITY=docling`:

- Backend and Worker POST to `DOCLING_SERVICE_URL + /v1/convert/file` with the uploaded file.
- If Docling fails, Curatore automatically falls back to the internal extraction-service (if configured).

Docling request options sent by Curatore:

- Output format: `output_format=markdown`
- Image handling: `image_export_mode=placeholder`
- Pipeline: `pipeline_type=standard`
- OCR: `enable_ocr=true`, `ocr_engine=auto`
- Tables: `table_mode=accurate`
- Annotations & images: `include_annotations=true`, `generate_picture_images=false`, `include_images=false`

Notes on compatibility:

- Options are sent as both query params and form fields (strings only) to satisfy differing Docling builds and encoders.
- If images still appear as embedded, ensure your Docling build honors `image_export_mode` or `imageExportMode`. Some versions only support one of these.

Troubleshooting Docling:

- Logs show which extractor ran and any Docling status/errors. Check `curatore-worker` logs.
- Common issues:
  - “Invalid type for value. Expected primitive type”: update to latest Curatore; options are now sent as primitives.
  - Images embedded instead of placeholders: confirm Docling version and try setting only one key via a reverse proxy rule, e.g. force `image_export_mode=placeholder`.
  - Endpoint mismatch: Curatore uses `POST /v1/convert/file`. If your Docling exposes a different endpoint, set `document_service.docling_extract_path` accordingly in code.

### **Async Processing with Celery**

Curatore processes documents asynchronously using Celery + Redis so requests return immediately and progress can be tracked per file.

- Broker: `CELERY_BROKER_URL` (default `redis://redis:6379/0`)
- Results: `CELERY_RESULT_BACKEND` (default `redis://redis:6379/1`)
- Default queue: `CELERY_DEFAULT_QUEUE` (default `processing`)
- Worker: auto-started via `docker-compose` as `curatore-worker`

Recommended settings (override via env):

- `CELERY_ACKS_LATE=true` — requeue if worker dies
- `CELERY_PREFETCH_MULTIPLIER=1` — avoid task hoarding
- `CELERY_MAX_TASKS_PER_CHILD=50` — bound memory growth
- `CELERY_TASK_SOFT_TIME_LIMIT=600`, `CELERY_TASK_TIME_LIMIT=900`
- `CELERY_RESULT_EXPIRES=259200` (3 days)
- `JOB_LOCK_TTL_SECONDS=3600` — enforce single active job per document
- `JOB_STATUS_TTL_SECONDS=259200` — retain job metadata
- `ALLOW_SYNC_PROCESS=false` — set `true` only for tests (`?sync=true`)

Job & queue endpoints (v1):

- Enqueue document: `POST /api/v1/documents/{document_id}/process`
  - Returns `{ job_id, document_id, status: 'queued', enqueued_at }`
  - Returns `409` with `{ active_job_id }` if a job is already running for that document
- Poll job: `GET /api/v1/jobs/{job_id}` → `PENDING|STARTED|SUCCESS|FAILURE` (+ `result` on success)
- Last job for a document: `GET /api/v1/jobs/by-document/{document_id}`
- Batch enqueue: `POST /api/v1/documents/batch/process` → `{ batch_id, jobs, conflicts }`
- Queue health: `GET /api/v1/system/queues` → `{ enabled, broker, result_backend, queue, redis_ok, pending, workers, running, processed, total }`
- Queue summary by batch or jobs: `GET /api/v1/system/queues/summary?batch_id=...` or `?job_ids=jid1,jid2`

### **LLM Endpoint Examples**

#### **Local LLM (Ollama)**
```bash
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=llama3.1:8b
OPENAI_VERIFY_SSL=false
```

#### **OpenWebUI**
```bash
OPENAI_BASE_URL=http://localhost:3000/v1
OPENAI_API_KEY=your-openwebui-api-key
OPENAI_MODEL=your-model-name
```

#### **LM Studio**
```bash
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio
OPENAI_MODEL=local-model
OPENAI_VERIFY_SSL=false
```

---

## 📋 **Usage Guide**

### **🌐 Web Interface**

1. **Upload Documents**
   - Drag & drop files or click "Choose Files"
   - Supports multiple file selection
   - Real-time file validation and size checking
   - Supported formats: PDF, DOCX, PPTX, TXT, Images

2. **Document Processing**
   - Automatic processing with intelligent conversion
   - Live progress tracking with emoji indicators
   - Quality score monitoring in real-time
   - Vector optimization for RAG applications

3. **Quality Review & Analysis**
   - View comprehensive processing statistics
   - Edit and re-score documents with inline editor
   - Review detailed quality scores and LLM feedback
   - Track RAG readiness status with visual indicators

4. **Export & Download Options**
   - **Individual Downloads**: Single processed markdown files
   - **ZIP Archives**: Multiple export options
     - Combined Archive: Individual files + merged document + processing summary
     - RAG-Ready Only: Filtered files meeting all quality thresholds
     - Custom Selection: User-selected files with metadata
   - **Processing Reports**: Detailed analysis and optimization status

### **🔌 API Usage (v1)**

Complete API documentation available at: **http://localhost:8000/docs**

#### **Basic Document Operations**
```bash
# Upload document
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -F "file=@document.pdf"

# Process document with auto-optimization
curl -X POST "http://localhost:8000/api/v1/documents/{id}/process" \
  -H "Content-Type: application/json" \
  -d '{"auto_optimize": true}'

# Get processing result
curl "http://localhost:8000/api/v1/documents/{id}/result"

# Get processed content
curl "http://localhost:8000/api/v1/documents/{id}/content"
```

#### **Download Operations**
```bash
# Download individual processed document
curl "http://localhost:8000/api/v1/documents/{id}/download" \
  -o processed_document.md

# Download RAG-ready files as ZIP
curl "http://localhost:8000/api/v1/documents/download/rag-ready?zip_name=rag_files.zip" \
  -o rag_ready_files.zip

# Bulk download with custom options
curl -X POST "http://localhost:8000/api/v1/documents/download/bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": ["doc1", "doc2", "doc3"],
    "download_type": "combined",
    "zip_name": "export.zip",
    "include_summary": true
  }' \
  -o bulk_export.zip
```

#### **Batch Processing**
```bash
# Process multiple documents
curl -X POST "http://localhost:8000/api/v1/documents/batch/process" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": ["doc1", "doc2", "doc3"],
    "options": {
      "auto_optimize": true,
      "quality_thresholds": {
        "conversion": 75,
        "clarity": 8,
        "completeness": 7,
        "relevance": 7,
        "markdown": 7
      }
    }
  }'

# Get batch processing status
curl "http://localhost:8000/api/v1/documents/batch/{batch_id}/status"

# Get batch results
curl "http://localhost:8000/api/v1/documents/batch/{batch_id}/results"
```

#### **System Monitoring**
```bash
# Test LLM connection
curl "http://localhost:8000/api/v1/llm/status"

# Check API health
curl "http://localhost:8000/api/v1/health"

# Get supported file formats
curl "http://localhost:8000/api/v1/config/supported-formats"

# Get default configuration
curl "http://localhost:8000/api/v1/config/defaults"

# System reset (development only)
curl -X POST "http://localhost:8000/api/v1/system/reset"

# Queue health (Celery/Redis)
curl "http://localhost:8000/api/v1/system/queues"

# Queue summary for a batch
curl "http://localhost:8000/api/v1/system/queues/summary?batch_id=YOUR_BATCH_ID"

# Queue summary for specific jobs
curl "http://localhost:8000/api/v1/system/queues/summary?job_ids=jid1,jid2"
```

---

## 📊 **Quality Metrics**

### **Conversion Quality (0-100 Scale)**
- **Content Coverage** (50% weight): Ratio of extracted vs. original content
- **Structure Preservation** (30% weight): Detection and preservation of headings, lists, tables
- **Readability** (20% weight): Character encoding quality and line length analysis

### **LLM Evaluation (1-10 Scale Each)**
- **Clarity**: Document structure, readability, logical flow, and coherence
- **Completeness**: Information preservation, missing content detection, coverage analysis
- **Relevance**: Content focus assessment, identification of unnecessary information
- **Markdown Quality**: Formatting consistency, structure quality, syntax correctness

### **RAG Readiness Criteria**
Documents achieve "RAG Ready" status when they meet all configured thresholds and demonstrate:
- ✅ **Vector Database Optimization**: Content structured for efficient chunking
- ✅ **Semantic Search Ready**: Clear section boundaries and context preservation
- ✅ **Independent Chunk Meaning**: Each section maintains context without dependencies
- ✅ **Q&A Performance**: Content optimized for question-answering scenarios

---

## 📦 **Export & Archive Features**

### **Archive Types**

#### **1. Standard Archives**
```
curatore_export_20250827_143022.zip
├── processed_documents/
│   ├── document1.md
│   ├── document2.md
│   └── document3.md
└── PROCESSING_SUMMARY_20250827_143022.md
```

#### **2. Combined Archives**
```
curatore_combined_export_20250827_143022.zip
├── individual_files/
│   ├── document1.md
│   ├── document2.md
│   └── document3.md
├── COMBINED_EXPORT_20250827_143022.md
└── PROCESSING_SUMMARY_20250827_143022.md
```

#### **3. RAG-Ready Archives**
- Contains only documents meeting all quality thresholds
- Filtered for production readiness
- Includes optimization status indicators and quality metrics

### **Combined Markdown Features**
- **Automatic Header Hierarchy**: Prevents conflicts when merging documents
- **Document Summaries**: Each section includes processing metadata and quality scores
- **Quality Indicators**: Visual status (✅ RAG Ready, ⚠️ Needs Improvement, 🎯 Vector Optimized)
- **Unified Structure**: Consistent formatting across all merged content

---

## 🔧 **Development**

### **Project Structure**
```
curatore/
├── files/                       # File storage (Docker volume mount)
│   ├── uploaded_files/          # User-uploaded documents
│   ├── processed_files/         # Converted markdown files
│   └── batch_files/             # Local files for batch processing
├── frontend/                    # Next.js TypeScript frontend (App Router)
│   ├── package.json             # Dependencies and scripts
│   ├── next.config.mjs          # Next.js configuration
│   ├── app/                     # App routes and layouts
│   ├── components/              # UI components
│   └── lib/                     # API client and helpers
├── backend/                     # FastAPI Python backend
│   ├── requirements.txt         # Python dependencies
│   ├── Dockerfile              # Backend container configuration
│   └── app/                     # Application source
│       ├── services/            # Core business logic (fully documented)
│       ├── api/                 # Versioned API routes and endpoints
│       │   └── v1/routers       # v1 endpoints
│       ├── models.py            # Pydantic data models and validation
│       ├── config.py            # Configuration management
│       └── main.py              # FastAPI application entry point
├── scripts/                     # Development and deployment scripts
│   ├── dev-up.sh               # Start development environment
│   ├── dev-down.sh             # Stop development environment
│   └── clean.sh                # Clean up containers and volumes
├── docker-compose.yml           # Development environment setup
├── .env.example                # Environment variable template
└── README.md                   # This file
```

### **Development Scripts**

```bash
# Start development environment (detached) with hot-reload
./scripts/dev-up.sh

# Tail logs (all or specific services)
./scripts/dev-logs.sh               # all services
./scripts/dev-logs.sh backend       # specific service

# Restart services (optionally rebuild if deps changed)
./scripts/dev-restart.sh worker
./scripts/dev-restart.sh --build backend

# Stop and remove services
./scripts/dev-down.sh

# Deep clean (volumes, images, orphans)
./scripts/clean.sh
```

Notes:
- Backend and Extraction run with live reload; code edits apply immediately.
- Worker runs under `watchmedo` and restarts on Python file changes.
- If you change Python dependencies (`backend/requirements.txt`) or Dockerfiles, run:
  `./scripts/dev-restart.sh --build backend worker`

### **Code Standards & Documentation**

All backend services follow comprehensive documentation standards:

- **Type Hints**: Complete type annotations for all parameters and return values
- **Docstrings**: Google/NumPy style documentation with usage examples
- **Error Handling**: Comprehensive exception handling with detailed error messages
- **Integration Patterns**: Clear documentation of service interactions
- **Performance Notes**: Optimization guidelines and best practices

### **Testing & Debugging**

```bash
# Test individual document processing
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -F "file=@test_document.pdf"

# Test LLM connectivity
curl "http://localhost:8000/api/v1/llm/status"

# Health check
curl "http://localhost:8000/api/v1/health"

# Download test files
curl "http://localhost:8000/api/v1/documents/download/rag-ready" -o test_rag.zip

# View processing logs
docker-compose logs -f backend | grep "Processing"
```

---

## 🚀 **Deployment**

### **Production Deployment**

```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Deploy with production configuration
docker-compose -f docker-compose.prod.yml up -d

# Monitor services
docker-compose -f docker-compose.prod.yml logs -f
```

### **Production Environment Considerations**

#### **System Requirements**
- **CPU**: OCR processing is CPU-intensive (recommend 4+ cores)
- **Memory**: 4GB+ RAM for document processing and LLM operations
- **Storage**: Plan for document storage (uploads + processed files + temporary ZIP files)
- **Network**: Consider bandwidth for ZIP downloads and LLM API calls

#### **Configuration Updates**
- **Remove `--reload`** from uvicorn command in backend Dockerfile
- **Use `next build && next start`** for frontend production build
- **Configure reverse proxy** (nginx) for SSL termination
- **Set up proper logging** with log rotation and monitoring
- **Use named volumes** instead of bind mounts for better security

#### **Security & Monitoring**
- **SSL/TLS**: Configure HTTPS with proper certificates
- **API Rate Limiting**: Implement rate limiting for API endpoints
- **File Validation**: Enhanced file type and content validation
- **Monitoring**: Set up health checks and alerting
- **Backup Strategy**: Regular backup of file storage volumes

---

## 📈 **Performance & Scalability**

### **Processing Optimization**
- **Sequential Batch Processing**: Prevents resource contention and memory issues
- **Intelligent Conversion Chains**: Multi-format fallback with performance-optimized paths
- **Memory Management**: Automatic cleanup of temporary files and processing artifacts
- **Configurable Quality Thresholds**: Balance between processing speed and output quality

### **File Management**
- **Docker Volume Mounts**: Persistent storage across container restarts
- **UUID-based Organization**: Efficient file naming and retrieval system
- **Automatic Cleanup**: Temporary file management with background cleanup processes
- **Storage Monitoring**: Track disk usage and implement cleanup policies

### **API Performance**
- **Async Processing**: Non-blocking document processing with progress tracking
- **Efficient Caching**: In-memory storage for processing results and metadata
- **Streaming Downloads**: Large ZIP files streamed to prevent memory issues
- **Connection Pooling**: Optimized LLM API connections with retry logic

---

## 🔍 **Monitoring & Debugging**

### **Comprehensive Logging**
- **Processing Pipeline**: Status tracking with emoji indicators and detailed timestamps
- **Error Tracking**: Stack traces with context information and recovery suggestions
- **Performance Metrics**: Processing times, file sizes, and resource usage
- **LLM Monitoring**: Connection status, response times, and error rates

### **Health Checks & Diagnostics**
- **API Health Endpoints**: System status and component health monitoring
- **LLM Connection Testing**: Real-time connectivity verification with detailed diagnostics
- **File System Validation**: Docker volume mount verification and permission checking
- **Quality Threshold Monitoring**: Pass/fail rate tracking across different document types

### **Debug Tools**
```bash
# Enable debug logging
export DEBUG=true

# View detailed processing logs
docker-compose logs -f backend | grep -E "(Processing|Error|Warning)"

# Monitor file operations
docker-compose exec backend ls -la /app/files/

# Check LLM connectivity
curl -v "http://localhost:8000/api/v1/llm/status"

# Validate configuration
curl "http://localhost:8000/api/v1/config/defaults"
```

---

## 🧩 **Frontend Configuration**

- `NEXT_PUBLIC_API_URL`: Base URL for the backend API (default `http://localhost:8000`).
- `NEXT_PUBLIC_JOB_POLL_INTERVAL_MS`: Poll interval for job/queue updates in the UI (e.g., `2500`).
- Frontend uses API path version `v1` by default (see `frontend/lib/api.ts`).

---

## 🧠 **Status Bar Insights**

- Shows API health, LLM connection, max upload size, and supported formats.
- Displays live queue metrics (queued, running, done, total) via `/api/v1/system/queues` and `/api/v1/system/queues/summary`.
- Shows backend version and API path version.

---

## 🤝 **Contributing**

### **Development Guidelines**

1. **Documentation Standards**
   - Follow established patterns in service files
   - Include comprehensive docstrings with usage examples
   - Document error handling and recovery strategies
   - Add integration patterns and performance notes

2. **Code Quality**
   ```bash
   # Format Python code
   black backend/app/
   isort backend/app/
   
   # Type checking
   mypy backend/app/
   
   # Linting
   flake8 backend/app/
   
   # Frontend linting
   cd frontend && npm run lint
   ```

3. **Testing Requirements**
   - Add unit tests for new service methods
   - Include integration tests for API endpoints
   - Test error handling and edge cases
   - Verify Docker container functionality

4. **Pull Request Process**
   - Create feature branches from main
   - Include tests and documentation updates
   - Update README.md if adding new features
   - Ensure all CI checks pass

---

## 🔐 **Security Considerations**

### **File Security**
- **Upload Validation**: Extension whitelist and MIME type verification
- **Content Sanitization**: Filename cleaning and path traversal prevention
- **Size Limits**: Configurable file size limits to prevent DoS attacks
- **Temporary File Management**: Automatic cleanup to prevent disk space issues

### **API Security**
- **CORS Configuration**: Restricted origins for production deployment
- **Input Validation**: Pydantic models with comprehensive validation
- **Error Handling**: Sanitized error messages to prevent information disclosure
- **SSL Configuration**: Flexible SSL verification for different deployment scenarios

### **Data Privacy**
- **Local Processing**: Documents processed locally without external transmission
- **Memory Management**: Automatic cleanup of sensitive data from memory
- **Log Security**: Sensitive information excluded from application logs
- **API Key Management**: Secure environment variable handling

---

## 📚 **API Documentation**

Complete interactive API documentation is available at **http://localhost:8000/docs** when running the application.

### **Key Endpoint Categories**

#### **Document Management**
- Upload, process, download, and delete operations
- Content editing with LLM improvement suggestions
- Processing status tracking and result retrieval

#### **Batch Operations**
- Multi-document processing with progress monitoring
- Bulk download and export functionality
- Quality threshold management across document sets

#### **Export & Archive**
- ZIP creation with multiple format options
- Combined document exports with merged content
- RAG-ready filtering based on quality thresholds

#### **System & Configuration**
- Health monitoring and diagnostic endpoints
- LLM connection testing and status reporting
- Configuration management and default settings

---

## 📄 **License**

This project is licensed under the [MIT License](LICENSE) - see the LICENSE file for details.

---

## 🙏 **Acknowledgments**

### **Core Dependencies**
- **[MarkItDown](https://github.com/microsoft/markitdown)**: Primary document conversion library
- **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)**: Robust image-based text extraction
- **[FastAPI](https://fastapi.tiangolo.com/)**: Modern, fast Python web framework
- **[Next.js](https://nextjs.org/)**: React framework for production-ready frontend
- **[OpenAI API](https://openai.com/api/)**: LLM integration for quality assessment

### **Community & Contributors**
- Built with ❤️ for the RAG and document processing community
- Special thanks to all contributors and beta testers
- Inspired by the need for high-quality, RAG-optimized document processing

---

**Ready to process your documents? Start with `./scripts/dev-up.sh` and visit http://localhost:3000!**
