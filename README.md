# Curatore v2 📚

*Transform documents into RAG-ready, semantically optimized content*

A modern multi-tier RAG (Retrieval Augmented Generation) document processing and optimization tool that converts, scores, and optimizes documents for vector database storage and semantic search.

## 🏗️ Architecture

**Curatore v2** features a modern multi-tier architecture with comprehensive documentation:

- **Frontend**: Next.js 14 (App Router) + TailwindCSS
- **Backend**: Python + FastAPI with fully documented services
- **Processing**: Document conversion, OCR, LLM optimization
- **Runtime**: Docker + docker-compose with hot-reload

## ✨ Features

### 🔄 Document Processing Pipeline

- **Multi-format support**: PDF, DOCX, images (PNG, JPG, JPEG, BMP, TIF, TIFF), Markdown, and text files
- **Intelligent conversion chain**: MarkItDown → format-specific converters → OCR fallbacks
- **High-quality extraction** with configurable OCR settings and Tesseract integration
- **Comprehensive error handling** with graceful degradation

### 🎯 Vector Database Optimization

- **Automatic optimization** for vector database chunking and retrieval
- **Context-rich formatting** ensures chunks are meaningful when retrieved independently
- **Semantic search ready** with keyword enhancement and consistent structure
- **LLM-powered optimization** with specialized prompts for RAG applications

### 📊 Quality Assessment & Scoring

- **Conversion quality scoring** (0-100) based on content coverage, structure, and legibility
- **LLM-powered evaluation** across four dimensions: Clarity, Completeness, Relevance, Markdown Compatibility
- **Configurable quality thresholds** for RAG readiness assessment
- **Automated threshold validation** for production readiness

### 📦 Advanced Download & Export Options

- **ZIP Archive Creation**: Bulk download multiple documents as organized ZIP files
- **Combined Markdown Export**: Single file containing all processed documents with adjusted hierarchy
- **RAG-Ready Filtering**: Download only documents that meet quality thresholds
- **Processing Summaries**: Detailed reports with quality metrics and processing statistics
- **Individual & Bulk Downloads**: Flexible export options for different use cases

### 🌐 Modern Web Interface

- **Drag & drop file upload** with real-time processing
- **Live processing status** with detailed feedback and quick download actions
- **Quality score visualization** with actionable insights
- **Batch processing support** with comprehensive statistics
- **Processing panel** with real-time logs and quick export options

### 🔌 Flexible LLM Integration

- **OpenAI API compatibility** with custom endpoint support
- **Local LLM support**: Ollama, LM Studio, OpenWebUI
- **Connection testing** with detailed status reporting
- **Comprehensive error handling** and fallback mechanisms

## 🏛️ Backend Architecture

### Fully Documented Services

The backend consists of comprehensively documented services with modern Python standards:

#### Core Services
- **`document_service.py`** - Complete document processing pipeline
  - Multi-format conversion with intelligent fallback chains
  - OCR processing with Tesseract integration
  - Quality scoring and threshold validation
  - LLM integration for optimization and evaluation
  - Batch processing capabilities
  - File management with Docker volume support

- **`llm_service.py`** - Large Language Model integration
  - Document quality evaluation (4 dimensions)
  - Content improvement with custom prompts
  - Vector database optimization for RAG
  - Document summarization
  - Connection testing and status monitoring
  - SSL verification control for local deployments

- **`storage_service.py`** - In-memory storage management
  - Thread-safe processing result storage
  - CRUD operations for individual and batch results
  - Automatic cross-referencing between batch and individual results
  - Complete system reset functionality

- **`zip_service.py`** - ZIP archive creation service
  - Individual document archives with summaries
  - Combined exports with merged documents
  - Detailed processing summaries with quality metrics
  - Header hierarchy adjustment for combined documents
  - Temporary file management with automatic cleanup

#### Documentation Standards
- **Comprehensive docstrings** following Google/NumPy conventions
- **Complete type hints** for all parameters and return values
- **Usage examples** for all major methods
- **Error handling documentation** with failure modes and recovery
- **Integration patterns** showing service interactions
- **Performance considerations** and optimization notes

### API Structure
```
backend/app/
├── services/                    # Core business logic services
│   ├── document_service.py     # Document processing pipeline
│   ├── llm_service.py          # LLM integration and evaluation
│   ├── storage_service.py      # In-memory storage management
│   └── zip_service.py          # Archive creation and export
├── api/                        # API routing and endpoints
│   └── routers/
│       ├── documents.py        # Document processing endpoints
│       └── system.py           # System health and configuration
├── models.py                   # Pydantic data models
├── config.py                   # Application configuration
└── main.py                     # FastAPI application setup
```

## 🚀 Quick Start

### Prerequisites

- **Docker Desktop** (recommended)
- OR: **Node.js 18+** and **Python 3.11+** for manual setup

### Using Docker (Recommended)

1. **Clone and setup**:
```bash
git clone <repository-url>
cd curatore
cp .env.example .env
# Edit .env with your API configuration
```

2. **Start the services**:
```bash
./scripts/dev-up.sh
```

3. **Access the applications**:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000  
- **API Documentation**: http://localhost:8000/docs

### Manual Installation

1. **Backend setup**:
```bash
cd backend
pip install -r requirements.txt
# Install Tesseract OCR (see below)
uvicorn app.main:app --reload
```

2. **Frontend setup**:
```bash
cd frontend
npm install
npm run dev
```

3. **Install Tesseract OCR**:
   - **Ubuntu/Debian**: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
   - **macOS**: `brew install tesseract`
   - **Windows**: Download from [GitHub releases](https://github.com/UB-Mannheim/tesseract/wiki)

## ⚙️ Configuration

### Environment Variables

```bash
# LLM Configuration
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_VERIFY_SSL=true
OPENAI_TIMEOUT=60
OPENAI_MAX_RETRIES=3

# OCR Configuration  
OCR_LANG=eng
OCR_PSM=3

# File Storage
BATCH_DIR=files/batch_files
UPLOAD_DIR=files/uploaded_files
PROCESSED_DIR=files/processed_files  
MAX_FILE_SIZE=52428800

# Quality Thresholds
DEFAULT_CONVERSION_THRESHOLD=70
DEFAULT_CLARITY_THRESHOLD=7
DEFAULT_COMPLETENESS_THRESHOLD=7
DEFAULT_RELEVANCE_THRESHOLD=7
DEFAULT_MARKDOWN_THRESHOLD=7
```

### LLM Endpoint Examples

**Local LLM (Ollama)**:
```bash
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=llama3.1:8b
```

**OpenWebUI**:
```bash
OPENAI_BASE_URL=http://localhost:3000/v1
OPENAI_API_KEY=your-openwebui-api-key
```

**LM Studio**:
```bash
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio
```

## 📋 Usage Guide

### Web Interface

1. **Upload Documents**
   - Drag & drop files or click to browse
   - Supports multiple file selection
   - Real-time file validation

2. **Processing**
   - Automatic processing with vector optimization
   - Live progress tracking in processing panel
   - Quality score monitoring

3. **Review Results**
   - View processing statistics
   - Edit and re-score documents inline
   - Review quality scores and feedback

4. **Download & Export**
   - **Individual Downloads**: Single markdown files
   - **ZIP Archives**: Bulk downloads with multiple options:
     - Combined Archive: Individual files + merged document + summary
     - Selected Files: Custom selection as ZIP
     - RAG-Ready Only: Files meeting quality thresholds
   - **Quick Downloads**: Direct access from processing panel
   - **Processing Reports**: Detailed statistics and quality analysis

### API Usage

The FastAPI backend provides comprehensive RESTful endpoints with full OpenAPI documentation:

#### Basic Document Operations
```bash
# Upload document
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "file=@document.pdf"

# Process document  
curl -X POST "http://localhost:8000/api/documents/{id}/process" \
  -H "Content-Type: application/json" \
  -d '{"auto_optimize": true}'

# Get processing result
curl "http://localhost:8000/api/documents/{id}/result"
```

#### Download Operations
```bash
# Download individual document
curl "http://localhost:8000/api/documents/{id}/download" \
  -o processed_document.md

# Download RAG-ready files as ZIP
curl "http://localhost:8000/api/documents/download/rag-ready?zip_name=my_rag_files.zip" \
  -o rag_ready_files.zip

# Bulk download as ZIP
curl -X POST "http://localhost:8000/api/documents/download/bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": ["doc1", "doc2", "doc3"],
    "download_type": "combined",
    "zip_name": "my_export.zip",
    "include_summary": true
  }' \
  -o bulk_export.zip
```

#### Batch Processing
```bash
# Process multiple documents
curl -X POST "http://localhost:8000/api/documents/batch/process" \
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
```

#### System Monitoring
```bash
# Test LLM connection
curl "http://localhost:8000/api/llm/status"

# Check API health
curl "http://localhost:8000/api/health"

# Get supported formats
curl "http://localhost:8000/api/config/supported-formats"
```

See full API documentation at: **http://localhost:8000/docs**

## 📊 Quality Metrics

### Conversion Quality (0-100)

- **Content Coverage** (50% weight): Ratio of extracted vs. original content
- **Structure Preservation** (0-80 points): Headings, lists, tables detection  
- **Readability** (0-20 points): Character encoding and line length analysis

### LLM Evaluation (1-10 each)

- **Clarity**: Document structure, readability, logical flow
- **Completeness**: Information preservation, missing content detection
- **Relevance**: Content focus, unnecessary information identification  
- **Markdown Quality**: Formatting consistency, structure quality

### RAG Readiness

Documents are "RAG Ready" when they meet all configured thresholds and are optimized for:

- Vector database chunking
- Semantic search retrieval
- Independent chunk meaning
- Question-answer performance

## 📦 Download & Export Features

### Archive Types

1. **Standard Archives**
   ```
   curatore_export_20250827_143022.zip
   ├── processed_documents/
   │   ├── document1.md
   │   ├── document2.md
   │   └── document3.md
   └── PROCESSING_SUMMARY_20250827_143022.md
   ```

2. **Combined Archives**
   ```
   curatore_combined_export_20250827_143022.zip
   ├── individual_files/
   │   ├── document1.md
   │   ├── document2.md
   │   └── document3.md
   ├── COMBINED_EXPORT_20250827_143022.md
   └── PROCESSING_SUMMARY_20250827_143022.md
   ```

3. **RAG-Ready Archives**
   - Contains only documents meeting all quality thresholds
   - Filtered for production readiness
   - Includes optimization status indicators

### Combined Markdown Features

- **Adjusted Header Hierarchy**: Headers automatically nested to prevent conflicts
- **Document Summaries**: Each section includes processing metadata and quality scores
- **Quality Indicators**: Visual status indicators (✅ RAG Ready, ⚠️ Needs Improvement, 🎯 Vector Optimized)
- **Unified Structure**: Consistent formatting across all merged documents

## 🔧 Development

### Project Structure

```
curatore-v2/
├── files/                       # Main file storage directory
│   ├── uploaded_files/          # User-uploaded documents
│   ├── processed_files/         # Processed markdown files
│   └── batch_files/             # Local files for batch processing
├── frontend/                    # Next.js TypeScript frontend
├── backend/                     # FastAPI Python backend
│   └── app/
│       ├── services/            # Fully documented core services
│       │   ├── document_service.py  # Document processing pipeline
│       │   ├── llm_service.py       # LLM integration service
│       │   ├── storage_service.py   # In-memory storage management
│       │   └── zip_service.py       # ZIP archive creation service
│       ├── api/                 # API routing
│       ├── models.py            # Pydantic data models
│       ├── config.py            # Application configuration
│       └── main.py              # FastAPI application setup
├── docker-compose.yml           # Development setup
├── .env.example                 # Environment template
└── README.md                    # This file
```

### Code Documentation

All backend services are comprehensively documented with:

- **Modern Python standards**: Type hints, docstrings, error handling
- **Usage examples**: Practical code examples for each major method
- **Integration patterns**: How services work together
- **Error handling**: Comprehensive coverage of failure modes
- **Performance considerations**: Optimization notes and best practices

### Running Development Environment

```bash
# Start all services
./scripts/dev-up.sh

# Stop services
./scripts/dev-down.sh

# Clean up (removes containers, images, volumes)
./scripts/clean.sh

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Testing Features

```bash
# Test individual document download
curl "http://localhost:8000/api/documents/{doc_id}/download"

# Test RAG-ready ZIP download
curl "http://localhost:8000/api/documents/download/rag-ready" -o rag_files.zip

# Test LLM connection
curl "http://localhost:8000/api/llm/status"

# Check API health
curl "http://localhost:8000/api/health"
```

## 🚀 Deployment

### Production Docker

```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Deploy with production configuration
docker-compose -f docker-compose.prod.yml up -d
```

### Environment Considerations

- **CPU**: OCR processing is CPU-intensive
- **Memory**: Large documents require sufficient RAM  
- **Storage**: Plan for document and output storage (ZIP files are created in temp directory)
- **LLM API**: Consider rate limits and costs for OpenAI API or local LLM requirements
- **Network**: ZIP downloads may be large for bulk operations

## 📈 Performance & Scalability

### Processing Performance
- **Sequential batch processing** prevents resource contention
- **Intelligent conversion chains** with optimized fallback strategies
- **Memory-efficient** processing with automatic cleanup
- **Configurable quality thresholds** for performance vs. quality trade-offs

### File Management
- **Docker volume mounts** for persistent storage
- **Automatic file cleanup** on startup and reset
- **Temporary file management** with background cleanup
- **Efficient file organization** with UUID-based naming

## 🔍 Monitoring & Debugging

### Comprehensive Logging
- **Processing pipeline status** with emoji indicators
- **Error tracking** with detailed stack traces
- **Performance metrics** with processing time tracking
- **LLM interaction monitoring** with connection status

### Health Checks
- **API health endpoints** for monitoring
- **LLM connection testing** with detailed status
- **File system validation** with Docker volume checks
- **Quality threshold monitoring** with pass/fail tracking

## 🤝 Contributing

### Development Guidelines
- **Follow documentation standards** established in service files
- **Add comprehensive docstrings** for all new methods
- **Include usage examples** in documentation
- **Add proper error handling** with logging
- **Write type hints** for all parameters and returns

### Code Standards
```bash
# Code formatting
black backend/app/
isort backend/app/

# Type checking
mypy backend/app/

# Testing
pytest backend/tests/
```

## 📚 API Documentation

Complete API documentation is available at **http://localhost:8000/docs** when running the application.

### Key Endpoints

- **Document Management**: Upload, process, download, delete
- **Batch Processing**: Multi-document processing with options
- **Quality Assessment**: Threshold configuration and evaluation
- **Export Operations**: ZIP creation, combined exports, RAG-ready filtering
- **System Health**: Connection testing, configuration, monitoring

## 🔐 Security Considerations

- **File upload validation** with extension and size limits
- **Content sanitization** with filename cleaning
- **SSL verification control** for local LLM deployments
- **API key management** with environment variable configuration
- **Temporary file cleanup** to prevent disk space issues

## 📝 License

[Add your license information here]

## 🙏 Acknowledgments

- **MarkItDown**: Primary document conversion library
- **Tesseract OCR**: Image-based text extraction
- **FastAPI**: Modern Python web framework
- **Next.js**: React framework for the frontend
- **OpenAI API**: LLM integration for quality assessment

---

*Built with ❤️ for the RAG community*