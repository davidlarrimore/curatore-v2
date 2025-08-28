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

5. **System Monitoring**
   - LLM connection status
   - API health checks
   - Processing statistics

### API Usage

The FastAPI backend provides comprehensive RESTful endpoints:

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

See full API documentation at: http://localhost:8000/docs

## 📦 Download & Export Features

### Download Types

1. **Individual Downloads** (`.md` files)
   - Single processed markdown files
   - Optimized for vector databases
   - Direct file access for testing

2. **ZIP Archives**
   - **Combined Archive**: Includes individual files, merged document, and processing summary
   - **Selected Files**: Custom selection of processed documents
   - **RAG-Ready Only**: Files that pass all quality thresholds
   - **Processing Summary**: Statistics and quality reports

3. **Quick Downloads**
   - Available directly from the processing panel
   - One-click access to RAG-ready files
   - Immediate download after processing completion

### Archive Structure

When downloading ZIP archives, files are organized as follows:

```
curatore_export_20250827_143022.zip
├── individual_files/           # Original processed files
│   ├── document1.md
│   ├── document2.md
│   └── document3.md
├── COMBINED_EXPORT_*.md        # All documents merged with adjusted hierarchy
└── PROCESSING_SUMMARY_*.md     # Detailed processing report with quality metrics
```

### Combined Markdown Features

- **Adjusted Header Hierarchy**: Headers are automatically nested to prevent conflicts
- **Document Summaries**: Each section includes processing metadata and quality scores
- **Quality Indicators**: Visual status indicators for RAG readiness and optimization
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
│       ├── services/
│       │   ├── zip_service.py   # NEW: ZIP archive creation service
│       │   ├── document_service.py
│       │   ├── llm_service.py
│       │   └── storage_service.py
│       └── models.py            # Updated with ZIP-related models
├── docker-compose.yml           # Development setup
├── .env.example                 # Environment template
└── README.md                    # This file
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

### Testing Download Features

```bash
# Test individual document download
curl "http://localhost:8000/api/documents/{doc_id}/download"

# Test RAG-ready ZIP download
curl "http://localhost:8000/api/documents/download/rag-ready" -o rag_files.zip

# Test bulk ZIP download
curl -X POST "http://localhost:8000/api/documents/download/bulk" \
  -H "Content-Type: application/json" \
  -d '{"document_ids": ["doc1", "doc2"], "download_type": "combined"}' \
  -o bulk_export.zip

# Test LLM connection
curl "http://localhost:8000/api/llm/status"

# Check API health
curl "http://localhost:8000/api/health"
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

## 📥 Export Formats & Use Cases

### For RAG Implementation

1. **Download RAG-Ready ZIP**: Contains only documents that pass all quality thresholds
2. **Use Vector Optimized files**: Enhanced structure for better semantic search
3. **Import Combined Export**: Single file for bulk vector database import

### For Review & Quality Assurance

1. **Download Processing Summary**: Detailed quality metrics and improvement suggestions
2. **Combined Archive**: Complete export with individual files and merged document
3. **Individual Downloads**: File-by-file review and testing

### For Production Deployment

1. **RAG-Ready Files**: Production-ready documents for immediate use
2. **Quality Reports**: Documentation for compliance and quality assurance
3. **Bulk Processing**: Batch operations with comprehensive statistics

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
- **LLM API**: Consider rate limits and costs
- **Network**: ZIP downloads may be large for bulk operations

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

**ZIP Download Issues**:
- Check available disk space for temporary files
- Verify document processing completed successfully
- Review browser console for download errors
- Ensure all selected documents exist in processed directory

### Performance Tips

**Large Batch Processing**:
- Process files in smaller batches if memory is limited
- Monitor processing panel for real-time status
- Use quality thresholds to filter results before download

**ZIP Archive Optimization**:
- Combined archives include both individual and merged files
- RAG-ready downloads filter automatically by quality scores
- Processing summaries provide detailed quality metrics