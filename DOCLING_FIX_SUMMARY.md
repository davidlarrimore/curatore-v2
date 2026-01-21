# Docling Integration Fix Summary

## Issues Found and Fixed

### 1. **Outdated API Parameter Names** ✅ FIXED
The Docling Serve API changed parameter names in v1.9.0, but the code was using old names.

**Changes Made:**
| Old Parameter | New Parameter | Type Change |
|--------------|---------------|-------------|
| `output_format` | `to_formats` | String → Array |
| `pipeline_type` | `pipeline` | Rename |
| `enable_ocr` | `do_ocr` | Rename |
| `include_annotations` | *(removed)* | Invalid |
| `generate_picture_images` | *(removed)* | Invalid |

**File:** `backend/app/services/extraction/docling.py:54-111`

### 2. **Incorrect Parameter Transmission** ✅ FIXED
Parameters were being sent as **query strings** (in URL) instead of **form data** (multipart/form-data).

**Before:**
```python
return await client.post(
    url,
    headers=headers,
    params=params,      # ❌ Query string
    files=files,
    data=params
)
```

**After:**
```python
return await client.post(
    url,
    headers=headers,
    files=files,
    data=form_data      # ✅ Form data only
)
```

**File:** `backend/app/services/extraction/docling.py:163-191`

### 3. **Format Support Clarification** ℹ️ DOCUMENTED
Docling **does not support plain .txt files**. This is a Docling limitation, not a bug.

## Service Comparison

### Internal Extraction Service (Port 8010)
**Technology:** MarkItDown + Tesseract OCR

**Supported Formats:**
- ✅ PDF (.pdf)
- ✅ Word (.doc, .docx)
- ✅ PowerPoint (.ppt, .pptx)
- ✅ Excel (.xls, .xlsx)
- ✅ CSV (.csv)
- ✅ Text (.txt, .md) ← **TXT supported**
- ✅ Images (.png, .jpg, .jpeg, .gif, .tif, .tiff, .bmp)

**Best For:**
- Simple text extraction
- Plain text files
- Quick conversions
- Basic OCR needs

### External Docling Service (Port 5151/5001)
**Technology:** IBM Docling Serve (dlparse_v4)

**Supported Formats:**
- ✅ PDF (.pdf)
- ✅ Word (.docx)
- ✅ PowerPoint (.pptx)
- ✅ Excel (.xlsx)
- ✅ HTML (.html, .htm)
- ✅ Markdown (.md)
- ✅ CSV (.csv)
- ✅ Images (image formats)
- ✅ AsciiDoc (.asciidoc)
- ✅ XML (xml_uspto, xml_jats, mets_gbs)
- ✅ Audio (.audio)
- ✅ VTT (.vtt)
- ❌ Plain Text (.txt) ← **TXT NOT supported**

**Best For:**
- Complex PDFs with rich layouts
- Academic papers
- Technical documents
- Advanced table extraction
- Documents requiring structure preservation

## Testing Results

### Docling Service ✅ Working
```bash
# Test with markdown file
curl -X POST "http://localhost:5151/v1/convert/file" \
  -F "files=@test.md" \
  -F "to_formats=md" \
  -F "do_ocr=true" \
  -F "pipeline=standard"

# Response: 200 OK
{
  "document": {
    "filename": "test.md",
    "md_content": "# Test Document...",
    "status": "success"
  }
}
```

### Internal Extraction Service ✅ Working
```bash
# Test with markdown file
curl -X POST "http://localhost:8010/api/v1/extract" \
  -F "file=@test.md"

# Response: 200 OK
{
  "filename": "test.md",
  "content_markdown": "# Test Document...",
  "method": "text"
}
```

## Configuration Recommendations

### When to Use Each Service

**Use Internal Extraction Service when:**
- Processing plain text files (.txt)
- Simple document extraction needs
- Fast processing is priority
- Lower resource usage desired

**Use Docling Service when:**
- Processing complex PDFs with tables/layouts
- Academic or technical documents
- Rich formatting preservation needed
- Advanced OCR capabilities required

### Docker Compose Configuration

The services are configured correctly in `docker-compose.yml`:

```yaml
# Internal extraction service (always enabled)
extraction:
  container_name: curatore-extraction
  ports:
    - "8010:8010"
  # Uses MarkItDown + Tesseract

# External Docling service (profile-based)
docling:
  profiles:
    - docling
  image: ghcr.io/docling-project/docling-serve-cpu:latest
  ports:
    - "5151:5001"
```

**To enable Docling:**
```bash
# Start with Docling
docker-compose --profile docling up -d

# Or set environment variable
export ENABLE_DOCLING_SERVICE=true
./scripts/dev-up.sh
```

## Error Messages Decoded

### "404 Not Found: Task result not found"
**Cause:** File format not supported by Docling (e.g., .txt files)

**Solution:** Use internal extraction service for unsupported formats, or convert to supported format

### "output_format: field required"
**Cause:** Using old parameter names

**Solution:** ✅ Fixed - code now uses `to_formats` instead of `output_format`

## Files Modified

1. `backend/app/services/extraction/docling.py`
   - Updated `_get_docling_params()` method (lines 54-111)
   - Fixed parameter transmission in `extract()` method (lines 163-191)

## Next Steps

1. ✅ **Backend and worker restarted** with updated code
2. ✅ **Both services tested** and working correctly
3. ℹ️ **Format routing recommended:** Route .txt files to internal service, complex PDFs to Docling

## References

- Docling Serve API: http://localhost:5151/docs
- Docling GitHub: https://github.com/docling-project/docling
- OpenAPI Spec: http://localhost:5151/openapi.json
