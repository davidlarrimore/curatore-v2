# Curatore v2 📚

*Transform documents into RAG-ready, semantically optimized content*

A modern multi-tier RAG (Retrieval Augmented Generation) document processing and optimization tool that converts, scores, and optimizes documents for vector database storage and semantic search.

## 🏗️ Architecture

**Curatore v2** features a modern multi-tier architecture:

- **Frontend**: Next.js 14 (App Router) + TailwindCSS
- **Backend**: Python + FastAPI  
- **Processing**: Document conversion, OCR, LLM optimization
- **Runtime**: Docker + docker-compose with hot-reload

## ✨ Features

### 🔄 Document Processing Pipeline
- **Multi-format support**: PDF, DOCX, images (PNG, JPG, JPEG, BMP, TIF, TIFF), Markdown, and text files
- **Intelligent conversion**: MarkItDown, format-specific fallbacks, OCR with Tesseract
- **High-quality extraction** with configurable OCR settings

### 🎯 Vector Database Optimization
- **Automatic optimization** for vector database chunking and retrieval
- **Context-rich formatting** ensures chunks are meaningful when retrieved independently
- **Semantic search ready** with keyword enhancement and consistent structure

### 📊 Quality Assessment & Scoring
- **Conversion quality scoring** (0-100) based on content coverage, structure, and legibility
- **LLM-powered evaluation** across four dimensions: Clarity, Completeness, Relevance, Markdown Compatibility
- **Configurable quality thresholds** for RAG readiness assessment

### 🌐 Modern Web Interface
- **Drag & drop file upload** with real-time processing
- **Live processing status** with detailed feedback
- **Quality score visualization** with actionable insights
- **Batch processing support** with comprehensive statistics

### 🔌 Flexible LLM Integration
- **OpenAI API compatibility** with custom endpoint support
- **Local LLM support**: Ollama, LM Studio, OpenWebUI
- **Connection testing** with detailed status reporting

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
UPLOAD_DIR=uploads
PROCESSED_DIR=processed  
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

1. **Upload Documents**: 
   - Drag & drop files or click to browse
   - Supports multiple file selection
   - Real-time file validation

2. **Processing**: 
   - Automatic processing with vector optimization
   - Live progress tracking
   - Quality score monitoring

3. **Review Results**:
   - View processing statistics
   - Download optimized documents  
   - Review quality scores and feedback

4. **System Monitoring**:
   - LLM connection status
   - API health checks
   - Processing statistics

### API Usage

The FastAPI backend provides RESTful endpoints:

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

# Download processed document
curl "http://localhost:8000/api/documents/{id}/download" \
  -o processed_document.md
```

See full API documentation at: http://localhost:8000/docs

## 🔧 Development

### Project Structure
```
curatore/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── main.py       # FastAPI application
│   │   ├── config.py     # Configuration management
│   │   ├── models.py     # Pydantic models
│   │   └── services/     # Business logic
│   │       ├── llm_service.py
│   │       └── document_service.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/             # Next.js frontend
│   ├── app/              # Next.js app directory
│   ├── components/       # React components
│   ├── package.json
│   └── Dockerfile
├── scripts/              # Utility scripts
├── docker-compose.yml
└── .env.example
```

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

### Testing

```bash
# Test LLM connection
curl "http://localhost:8000/api/llm/status"

# Check API health
curl "http://localhost:8000/api/health"

# Upload test document
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "file=@test.pdf"
```

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

### RAG Readiness
Documents are "RAG Ready" when they meet all configured thresholds and are optimized for:
- Vector database chunking
- Semantic search retrieval
- Independent chunk meaning
- Question-answer performance

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
- **Storage**: Plan for document and output storage
- **LLM API**: Consider rate limits and costs

## 🔄 Migration from v1

If migrating from Curatore v1 (Streamlit), use the migration script:

```bash
./scripts/migrate-to-v2.sh
```

See `MIGRATION_NOTES.md` for detailed migration information.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Troubleshooting

### Common Issues

**LLM Connection Failed**:
- Check API key and endpoint in `.env`
- Test connection via System Status panel
- Verify network connectivity

**OCR Poor Quality**:  
- Adjust `OCR_PSM` setting for document type
- Check `OCR_LANG` configuration
- Ensure Tesseract is properly installed

**File Upload Issues**:
- Check file size limits (`MAX_FILE_SIZE`)
- Verify supported formats
- Check browser console for errors

**Processing Failures**:
- Review API logs: `docker-compose logs backend`
- Check processing results for error details
- Verify all dependencies are installed

### Getting Help

- 📚 API Documentation: http://localhost:8000/docs
- 🔍 Health Checks: Use the System Status panel
- 📋 Logs: `docker-compose logs -f`
- 🐛 Issues: Create a GitHub issue with logs and configuration

---

**Curatore v2** - Modern, scalable document processing for RAG applications