# Extraction Services Reference

Curatore v2 supports two extraction engines for document processing:

For configuration defaults and Docling OCR toggles, see `docs/CONFIGURATION.md`.

## Quick Comparison

| Feature | Internal Extraction | Docling |
|---------|-------------------|---------|
| **Port** | 8010 | 5151 (→5001) |
| **Technology** | MarkItDown + Tesseract | IBM Docling Serve |
| **Plain Text (.txt)** | ✅ Supported | ❌ Not Supported |
| **PDF Processing** | ✅ Basic | ✅ Advanced |
| **Table Extraction** | Basic | Advanced |
| **Layout Preservation** | Basic | Advanced |
| **Resource Usage** | Low | Medium-High |
| **Startup** | Always On | Profile-based |

## Service URLs

```bash
# Internal Extraction Service
http://localhost:8010/api/v1/extract

# External Docling Service
http://localhost:5151/v1/convert/file
```

## Supported Formats

### Internal Extraction Service
- ✅ PDF, DOCX, PPTX, XLSX, XLS
- ✅ TXT, MD, CSV
- ✅ PNG, JPG, JPEG, GIF, TIF, TIFF, BMP

### Docling Service
- ✅ PDF, DOCX, PPTX, XLSX
- ✅ HTML, Markdown, CSV
- ✅ Images, AsciiDoc
- ✅ XML (uspto, jats, mets_gbs)
- ✅ Audio, VTT
- ❌ Plain Text (.txt) files

## API Examples

### Internal Extraction Service

**Request:**
```bash
curl -X POST "http://localhost:8010/api/v1/extract" \
  -F "file=@document.pdf"
```

**Response:**
```json
{
  "filename": "document.pdf",
  "content_markdown": "# Document Content...",
  "content_chars": 1234,
  "method": "markitdown",
  "ocr_used": false,
  "page_count": 5,
  "media_type": "application/pdf"
}
```

### Docling Service

**Request:**
```bash
curl -X POST "http://localhost:5151/v1/convert/file" \
  -F "files=@document.pdf" \
  -F "to_formats=md" \
  -F "do_ocr=true" \
  -F "pipeline=standard" \
  -F "table_mode=accurate"
```

**Response:**
```json
{
  "document": {
    "filename": "document.pdf",
    "md_content": "# Document Content...",
    "status": "success"
  },
  "processing_time": 2.5
}
```

## Docling Parameters (v1.9.0+)

### Core Parameters
- `to_formats`: Array of output formats (default: `["md"]`)
  - Options: `md`, `json`, `html`, `text`, `doctags`
- `pipeline`: Processing pipeline (default: `"standard"`)
  - Options: `standard`, `simple`, `vlm`
- `do_ocr`: Enable OCR (default: `true`)
- `ocr_engine`: OCR engine (default: `"easyocr"`)
  - Options: `easyocr`, `rapidocr`, `tesseract`, `ocrmac`, `tesserocr`

### Advanced Parameters
- `table_mode`: Table extraction mode (default: `"accurate"`)
  - Options: `fast`, `accurate`
- `image_export_mode`: Image handling (default: `"embedded"`)
  - Options: `embedded`, `placeholder`, `referenced`
- `include_images`: Extract images (default: `true`)
- `pdf_backend`: PDF parsing backend (default: `"dlparse_v4"`)
  - Options: `pypdfium2`, `dlparse_v1`, `dlparse_v2`, `dlparse_v4`

## Configuration in Curatore

### Backend Configuration
**File:** `backend/app/services/extraction/docling.py`

Default parameters sent to Docling:
```python
params = {
    "to_formats": ["md"],
    "image_export_mode": "embedded",
    "pipeline": "standard",
    "do_ocr": True,
    "ocr_engine": "easyocr",
    "table_mode": "accurate",
    "include_images": False,
}
```

### Docker Compose

**Enable Docling:**
```bash
# Option 1: Using profile
docker-compose --profile docling up -d

# Option 2: Using environment variable
export ENABLE_DOCLING_SERVICE=true
./scripts/dev-up.sh
```

**Environment Variables:**
```yaml
# Backend & Worker
- DOCLING_SERVICE_URL=http://docling:5001
- DOCLING_TIMEOUT=300
- DOCLING_VERIFY_SSL=true
```

## Engine Selection

Curatore automatically routes documents to the appropriate engine based on configuration:

### config.yml
```yaml
extraction:
  priority: auto  # auto | default | docling | none
  services:
    - name: extraction-service
      url: http://extraction:8010
      enabled: true
    - name: docling
      url: http://docling:5001
      enabled: true
```

### Selection Logic
1. **Priority: default** → Always use internal extraction service
2. **Priority: docling** → Use Docling if available, fallback to internal
3. **Priority: auto** → Choose best engine based on file type
   - Complex PDFs → Docling
   - Simple text/images → Internal
   - Unsupported by Docling → Internal
4. **Priority: none** → Disable extraction (error)

## Troubleshooting

### Docling Returns 404
**Error:** `Task result not found. Please wait for a completion status.`

**Cause:** File format not supported by Docling (e.g., .txt files)

**Solution:**
1. Check if format is supported (see list above)
2. Use internal extraction service for unsupported formats
3. Verify parameter names are correct (v1.9.0+ format)

### Docling Logs Show Format Error
**Error:** `Input document X.txt with format None does not match any allowed format`

**Cause:** Plain text files not supported by Docling

**Solution:** Route .txt files to internal extraction service automatically

### Parameters Not Working
**Error:** Parameters ignored or validation errors

**Cause:** Using old parameter names (pre-v1.9.0)

**Solution:** ✅ Fixed in latest code
- `output_format` → `to_formats` (array)
- `pipeline_type` → `pipeline`
- `enable_ocr` → `do_ocr`

## Health Checks

### Internal Service
```bash
curl http://localhost:8010/api/v1/system/health
# {"status":"ok","service":"extraction-service"}
```

### Docling Service
```bash
curl http://localhost:5151/health
# {"status":"ok"}
```

## Performance Considerations

### Internal Extraction Service
- **Speed:** Fast (< 1s for most documents)
- **Memory:** Low (< 500MB)
- **CPU:** Low-Medium

### Docling Service
- **Speed:** Slower (2-10s for complex PDFs)
- **Memory:** High (1-4GB)
- **CPU:** Medium-High
- **First Request:** Slow (model loading)

**Recommendation:** Use internal service for simple/text docs, Docling for complex PDFs with tables

## References

- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling Serve Documentation](https://docling-serve.readthedocs.io/)
- [MarkItDown](https://github.com/microsoft/markitdown)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)

## Updated: 2026-01-20
Docling API v1.9.0+ compatibility verified
