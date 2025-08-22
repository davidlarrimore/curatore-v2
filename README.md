# Curatore v2 📚

*Transform documents into RAG-ready, semantically optimized content*

A modern multi-tier RAG (Retrieval Augmented Generation) document processing and optimization tool that converts, scores, and optimizes documents for vector database storage and semantic search.

[![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?style=flat&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)

## 🏗️ Architecture

**Curatore v2** features a modern multi-tier architecture with complete separation of concerns:

- **Frontend**: Next.js 14 with TypeScript + TailwindCSS
- **Backend**: Python FastAPI with async processing
- **Processing Pipeline**: Document conversion, OCR, LLM optimization
- **Runtime**: Docker Compose with hot-reload development

## ✨ Features

### 🔄 4-Stage Processing Workflow
- **Stage 1: Upload & Select** - Local files or drag-and-drop upload with real-time validation
- **Stage 2: Process Documents** - Live processing with real-time logs and progress tracking
- **Stage 3: Review Results** - Quality assessment with live editor and optimization tools
- **Stage 4: Download Results** - Individual or bulk downloads with summary reports

### 🎯 Vector Database Optimization
- **Automatic optimization** for vector database chunking and retrieval
- **Context-rich formatting** ensures chunks are meaningful when retrieved independently
- **Semantic search ready** with keyword enhancement and consistent structure
- **Question-answer optimization** structures content for better RAG performance

### 📊 Quality Assessment & Scoring
- **Conversion quality scoring** (0-100) based on content coverage, structure, and legibility
- **LLM-powered evaluation** across four dimensions:
  - **Clarity** (1-10): Readability and structure
  - **Completeness** (1-10): Content preservation and coverage
  - **Relevance** (1-10): Information quality and focus
  - **Markdown Compatibility** (1-10): Formatting and structure quality
- **Configurable quality thresholds** for RAG readiness assessment
- **Real-time re-scoring** after content edits

### 🔧 Interactive Document Editor
- **Live markdown editor** with real-time editing capabilities
- **Vector DB optimization** button for on-demand document enhancement
- **Custom LLM improvements** with user-defined prompts
- **Save & re-score** functionality for iterative improvements
- **Side-by-side quality metrics** with detailed feedback

### 🚀 Modern Web Interface
- **Accordion-based workflow** with visual progress indication
- **Drag & drop file upload** with validation and preview
- **Real-time processing logs** with timestamps and status icons
- **Responsive design** that works on mobile and desktop
- **TypeScript throughout** for type safety and better development experience

### 🔌 Flexible LLM Integration
- **OpenAI API compatibility** with custom endpoint support
- **Local LLM support**: Ollama, LM Studio, OpenWebUI
- **Connection testing** with detailed status reporting
- **Configurable SSL** and timeout settings for local deployments
- **Multiple model support** with environment-based configuration

### 📁 Advanced File Management
- **Multiple upload methods**: Individual files, bulk selection, drag-and-drop
- **Local file processing**: Place files in backend folder for batch processing
- **Format validation**: Real-time validation of supported file types
- **Size limits**: Configurable file size restrictions
- **Automatic file organization** with UUID-based naming

## 🚀 Quick Start

### Prerequisites
- **Docker Desktop** (recommended for quick setup)
- OR: **Node.js 18+** and **Python 3.11+** for manual installation

### Using Docker (Recommended)

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd curatore-v2
   cp .env.example .env
   # Edit .env with your API configuration
   ```

2. **Start the services**:
   ```bash
   docker-compose up --build
   ```

3. **Access the applications**:
   - **Frontend**: http://localhost:3000
   - **Backend API**: http://localhost:8000
   - **API Documentation**: http://localhost:8000/docs

### Manual Installation

#### Backend Setup
```bash
cd backend
pip install -r requirements.txt

# Install Tesseract OCR (see platform-specific instructions below)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

#### Tesseract OCR Installation
- **Ubuntu/Debian**: `sudo apt-get install tesseract-ocr tesseract-ocr-eng`
- **macOS**: `brew install tesseract`
- **Windows**: Download from [GitHub releases](https://github.com/UB-Mannheim/tesseract/wiki)

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the root directory:

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
UPLOAD_DIR=uploads
PROCESSED_DIR=processed
MAX_FILE_SIZE=52428800

# Quality Thresholds (defaults)
DEFAULT_CONVERSION_THRESHOLD=70
DEFAULT_CLARITY_THRESHOLD=7
DEFAULT_COMPLETENESS_THRESHOLD=7
DEFAULT_RELEVANCE_THRESHOLD=7
DEFAULT_MARKDOWN_THRESHOLD=7

# API Settings
DEBUG=false
CORS_ORIGINS=["http://localhost:3000"]
```

### LLM Endpoint Examples

#### Local LLM (Ollama)
```bash
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=llama3.1:8b
OPENAI_VERIFY_SSL=false
```

#### OpenWebUI
```bash
OPENAI_BASE_URL=http://localhost:3000/v1
OPENAI_API_KEY=your-openwebui-api-key
OPENAI_MODEL=gpt-3.5-turbo
```

#### LM Studio
```bash
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio
OPENAI_MODEL=your-model-name
```

### OCR Configuration

- **OCR_LANG**: Language codes (e.g., 'eng', 'eng+spa', 'fra')
- **OCR_PSM**: Page Segmentation Mode (0-13)
  - 3: Fully automatic page segmentation (default)
  - 6: Uniform block of text
  - 8: Single word
  - 13: Raw line (for single text lines)

## 📋 Usage Guide

### 4-Stage Processing Workflow

#### Stage 1: Upload & Select Documents
1. **Choose source type**:
   - **Upload Documents**: Drag & drop or browse to upload files
   - **Local Documents**: Process files from `backend/batch_documents/` folder

2. **Select files**: Use checkboxes to select individual files or "Select All"

3. **Configure processing options**:
   - **Vector DB Optimization**: Enable automatic optimization for vector databases
   - **Quality Thresholds**: Set minimum scores for RAG readiness
   - **OCR Settings**: Configure language and page segmentation mode

4. **Start processing**: Click "Process X File(s)" to begin

#### Stage 2: Process Documents
- **Real-time progress**: Watch live progress bars and file-by-file status
- **Processing logs**: View timestamped logs with status icons
- **Statistics**: Monitor successful/failed/RAG-ready counts
- **Auto-advancement**: Automatically moves to review when complete

#### Stage 3: Review Results
- **File list**: Left panel shows all processed files with quality scores
- **Detailed review**: Right panel shows selected file details in two tabs:
  
  **Quality Scores Tab**:
  - Conversion quality metrics
  - LLM evaluation scores (Clarity, Completeness, Relevance, Markdown)
  - Pass/fail status for each threshold
  - Improvement recommendations

  **Live Editor Tab**:
  - Edit markdown content directly
  - **Save & Re-Score**: Update content and re-evaluate quality
  - **Vector Optimize**: Apply vector database optimization
  - **Custom Edit**: Use custom LLM prompts for improvements

#### Stage 4: Download Results
- **Individual downloads**: Download specific processed files
- **Bulk operations**: Download all files or only RAG-ready files
- **Summary reports**: Generate processing summary with statistics
- **File management**: Restart workflow or begin new session

### Quality Thresholds

Configure minimum scores for RAG readiness:
- **Conversion** (0-100): Document conversion quality
- **Clarity** (1-10): Readability and structure
- **Completeness** (1-10): Content preservation
- **Relevance** (1-10): Information quality
- **Markdown** (1-10): Formatting quality

Documents must meet **ALL** thresholds to be considered "RAG Ready".

### Supported File Formats

| Format | Extensions | Processing Method |
|--------|------------|-------------------|
| PDF | `.pdf` | Text extraction → OCR fallback |
| Word Documents | `.docx` | MarkItDown → python-docx fallback |
| Images | `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff` | Tesseract OCR |
| Text Files | `.txt`, `.md` | Direct loading |

## 🏗️ Development

### Project Structure

```
curatore-v2/
├── frontend/                    # Next.js TypeScript frontend
│   ├── app/
│   │   ├── process/page.tsx     # Main 4-stage workflow
│   │   ├── settings/page.tsx    # Settings management
│   │   ├── layout.tsx           # Root layout
│   │   └── page.tsx             # Home (redirects to process)
│   ├── components/
│   │   ├── ui/                  # Reusable UI components
│   │   │   └── Accordion.tsx    # Accordion navigation
│   │   ├── stages/              # Stage-specific components
│   │   │   ├── UploadSelectStage.tsx
│   │   │   ├── ProcessingStage.tsx
│   │   │   ├── ReviewStage.tsx
│   │   │   └── DownloadStage.tsx
│   │   └── Settings.tsx         # Settings component
│   ├── lib/
│   │   └── api.ts               # API service layer
│   ├── types/
│   │   └── index.ts             # TypeScript definitions
│   └── styles/
│       └── globals.css          # Global styles
├── backend/                     # FastAPI Python backend
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Configuration management
│   │   ├── models.py            # Pydantic models
│   │   └── services/            # Business logic
│   │       ├── llm_service.py   # LLM integration
│   │       └── document_service.py # Document processing
│   ├── uploads/                 # Uploaded files storage
│   ├── processed/               # Processed markdown files
│   ├── batch_documents/         # Local files for processing
│   ├── requirements.txt         # Python dependencies
│   └── Dockerfile               # Backend container
├── docker-compose.yml           # Development setup
├── .env.example                 # Environment template
└── README.md                    # This file
```

### Local Development Setup

1. **Start with Docker** (recommended):
   ```bash
   docker-compose up --build
   ```

2. **Or run services separately**:
   ```bash
   # Terminal 1 - Backend
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   
   # Terminal 2 - Frontend  
   cd frontend
   npm run dev
   ```

3. **Environment setup**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

### Development Features

- **Hot reload**: Both frontend and backend auto-reload on changes
- **TypeScript**: Full type safety with IntelliSense support
- **API documentation**: Automatic OpenAPI docs at `/docs`
- **Error handling**: Comprehensive error boundaries and logging
- **Development tools**: Type checking, linting, and formatting

### Testing

```bash
# Frontend type checking
cd frontend
npm run type-check

# Backend API testing
curl http://localhost:8000/api/health

# Test LLM connection
curl http://localhost:8000/api/llm/status

# Test file upload
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "file=@test.pdf"
```

## 🔧 API Reference

### Health & Status
- `GET /api/health` - System health check
- `GET /api/llm/status` - LLM connection status
- `GET /api/config/defaults` - Default configuration
- `GET /api/config/supported-formats` - Supported file formats

### File Management
- `GET /api/documents/uploaded` - List uploaded files
- `POST /api/documents/upload` - Upload a file
- `DELETE /api/documents/{id}` - Delete a document

### Processing
- `POST /api/documents/{id}/process` - Process single document
- `POST /api/documents/batch/process` - Process multiple documents
- `GET /api/documents/{id}/result` - Get processing result

### Content Management
- `GET /api/documents/{id}/content` - Get document content
- `PUT /api/documents/{id}/content` - Update document content
- `GET /api/documents/{id}/download` - Download processed file

See full API documentation at: http://localhost:8000/docs

## 📊 Quality Metrics

### Conversion Quality (0-100)
- **Content Coverage**: Ratio of extracted vs. original content
- **Structure Preservation**: Headings, lists, tables detection
- **Readability**: Character encoding and line length analysis

### LLM Evaluation (1-10 each)
- **Clarity**: Document structure, readability, logical flow
- **Completeness**: Information preservation, missing content detection
- **Relevance**: Content focus, unnecessary information identification
- **Markdown Quality**: Formatting consistency, structure quality

### RAG Readiness Criteria
Documents are "RAG Ready" when they:
- Meet all configured quality thresholds
- Have proper chunk-friendly structure
- Include sufficient context for independent retrieval
- Are optimized for semantic search

## 🚀 Deployment

### Production Docker

```bash
# Create production environment file
cp .env.example .env.prod
# Configure production settings

# Build and deploy
docker-compose -f docker-compose.prod.yml up -d
```

### Environment Considerations

- **CPU**: OCR processing is CPU-intensive
- **Memory**: Large documents require sufficient RAM (4GB+ recommended)
- **Storage**: Plan for document and output storage growth
- **LLM API**: Consider rate limits, costs, and latency
- **Network**: Ensure stable connection for LLM API calls

### Scaling

- **Horizontal scaling**: Deploy multiple backend instances behind load balancer
- **Queue system**: Add Redis/Celery for background processing
- **File storage**: Use S3/MinIO for production file storage
- **Database**: Add PostgreSQL for metadata and results persistence

## 🔄 Migration from v1

If migrating from Curatore v1 (Streamlit):

1. **Backup existing data**:
   ```bash
   cp -r v1/processed_documents v1/backup/
   ```

2. **Copy configuration**:
   ```bash
   # Extract settings from v1 app.py to .env
   ```

3. **Test migration**:
   ```bash
   # Process sample documents to verify compatibility
   ```

See `MIGRATION_NOTES.md` for detailed migration information.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes following the project structure
4. Add tests and documentation
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Development Guidelines

- **TypeScript**: Use strict typing throughout frontend
- **Python**: Follow PEP 8 style guidelines
- **Testing**: Add tests for new features
- **Documentation**: Update README and API docs
- **Components**: Keep components focused and reusable

## 🆘 Troubleshooting

### Common Issues

#### Frontend Issues
```bash
# Type errors
npm run type-check

# Build issues
npm run build

# Dependency issues
rm -rf node_modules package-lock.json
npm install
```

#### Backend Issues
```bash
# Import errors
pip install -r requirements.txt

# OCR not working
# Install Tesseract OCR for your platform

# LLM connection failed
curl http://localhost:8000/api/llm/status
```

#### Docker Issues
```bash
# Container issues
docker-compose down
docker-compose up --build

# Volume issues
docker-compose down -v
docker-compose up
```

### Performance Optimization

- **Large files**: Increase memory limits and timeout settings
- **Batch processing**: Process files in smaller batches
- **OCR optimization**: Adjust DPI and PSM settings
- **LLM optimization**: Use faster models or local deployment

### Getting Help

- 📚 **API Documentation**: http://localhost:8000/docs
- 🔍 **System Status**: Check the status panel in the UI
- 📋 **Logs**: Use `docker-compose logs -f` for detailed logs
- 🐛 **Issues**: Create GitHub issue with logs and configuration
- 💬 **Discussions**: Use GitHub Discussions for questions

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🎉 Acknowledgments

- **OpenAI** for GPT models and API
- **Anthropic** for Claude integration examples
- **Next.js** team for the excellent React framework
- **FastAPI** for the high-performance Python API framework
- **Tesseract** OCR engine for text extraction
- **MarkItDown** for document conversion
- **TailwindCSS** for beautiful, responsive styling

---

**Curatore v2** - Modern, scalable, type-safe document processing for RAG applications.

*Transform your documents into RAG-ready content with confidence.*