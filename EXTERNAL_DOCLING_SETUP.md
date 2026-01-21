# External Docling Configuration Summary

## Current Status

✅ **Network Configuration:** Working
- Docker containers can reach `http://host.docker.internal:5001`
- Health endpoint responds: `{"status":"ok"}`

✅ **API Version Detection:** Working
- External Docling v0.7.0 uses `/v1alpha/convert/file`
- Code auto-detects and uses correct endpoint

❌ **Conversion Endpoint:** Failing
- Returns `500 Internal Server Error` on conversion requests
- Health check passes, but actual document processing fails
- **This is an issue with your external Docling service, not Curatore**

## Configuration Changes Made

### 1. config.yml Updates

**Set external Docling as default:**
```yaml
extraction:
  default_engine: docling-external
```

**External Docling configuration:**
```yaml
- name: docling-external
  display_name: "Docling (Host Machine)"
  description: "Docling v0.7.0 running on host machine (macOS/Windows)"
  engine_type: docling
  service_url: http://host.docker.internal:5001
  enabled: true
  options:
    api_version: v1alpha  # Tells engine to use /v1alpha endpoints
    to_formats: ["md"]
    do_ocr: true
    ocr_engine: easyocr
    table_mode: accurate
```

**Internal Docling (Docker) - Disabled:**
```yaml
- name: docling-internal
  enabled: false  # Using external instead
```

### 2. Code Updates

**File:** `backend/app/services/extraction/docling.py`

**Auto-detection of API version:**
```python
@property
def default_endpoint(self) -> str:
    # Auto-detect v1alpha vs v1 based on service_url or options
    if 'v1alpha' in self.service_url.lower():
        return "/v1alpha/convert/file"
    if self.options and self.options.get('api_version') == 'v1alpha':
        return "/v1alpha/convert/file"
    return "/v1/convert/file"  # Default to v1.9.0+
```

**Version-aware parameters:**
```python
def _get_docling_params(self):
    is_alpha_api = 'v1alpha' in self.default_endpoint
    params = {
        "to_formats": ["md"],
        "do_ocr": True,
        # ... common params ...
    }

    if not is_alpha_api:
        # v1.9.0+ only: pipeline parameter
        params["pipeline"] = "standard"

    return params
```

## Troubleshooting External Docling

### Diagnostic Steps

1. **Check External Docling Logs:**
   ```bash
   # Look at the terminal where you're running Docling
   # Watch for errors like:
   # - Missing models
   # - Memory errors
   # - File format issues
   ```

2. **Test External Docling Directly:**
   ```bash
   # Test from your laptop (not Docker)
   echo "# Test" > test.md
   curl -X POST "http://localhost:5001/v1alpha/convert/file" \
     -F "files=@test.md" \
     -F "to_formats=md"
   ```

3. **Check Resource Usage:**
   ```bash
   # Docling needs adequate memory and CPU
   # Monitor with: top or Activity Monitor
   ```

### Common Issues and Fixes

#### Issue: "Internal Server Error" (500)
**Possible Causes:**
- Missing OCR models (EasyOCR, RapidOCR)
- Insufficient memory
- Corrupted model cache
- File format not properly detected

**Solutions:**
1. **Restart External Docling:**
   ```bash
   # Stop and restart your external Docling service
   # This will reload models and clear any stuck state
   ```

2. **Check Model Downloads:**
   ```bash
   # Docling downloads models on first use
   # If downloads failed, models might be missing
   # Look for download errors in Docling logs
   ```

3. **Increase Memory:**
   ```bash
   # Docling can use 2-4GB for complex documents
   # Ensure your system has enough free RAM
   ```

4. **Test with Different File:**
   ```bash
   # Try with a PDF instead of markdown
   # Some formats may work better than others
   ```

#### Issue: "Connection Refused"
**Cause:** External Docling not running or on wrong port

**Solution:**
```bash
# Verify Docling is running:
curl http://localhost:5001/health

# Should return: {"status":"ok"}
```

#### Issue: "Name or service not known"
**Cause:** Running test from wrong location (host vs container)

**Solution:**
- `host.docker.internal:5001` - Use from **inside** Docker containers
- `localhost:5001` - Use from **host** machine (your laptop)

### Version Compatibility

| Docling Version | API Endpoint | Pipeline Parameter | Status |
|----------------|--------------|-------------------|---------|
| v0.7.0 (alpha) | `/v1alpha/convert/file` | ❌ Not supported | Your external |
| v1.9.0+ | `/v1/convert/file` | ✅ Required | Docker internal |

## Fallback Options

If external Docling continues to fail, you have options:

### Option 1: Use Internal Docling (Docker)
```yaml
# config.yml
extraction:
  default_engine: docling-internal

engines:
  - name: docling-internal
    enabled: true  # Re-enable
```

**Pros:**
- Known working configuration
- No external dependencies
- Fully integrated

**Cons:**
- Different version (v1.9.0 vs v0.7.0)
- May have different behavior

### Option 2: Use Internal Extraction Service
```yaml
# config.yml
extraction:
  default_engine: extraction-service
```

**Pros:**
- Fast and lightweight
- Supports more formats (including .txt)
- Stable and tested

**Cons:**
- Basic extraction (not as advanced as Docling)
- Less sophisticated table handling

### Option 3: Upgrade External Docling
**Recommendation:** Upgrade your external Docling to v1.9.0+

```bash
# Update Docling (example, adjust for your setup)
pip install --upgrade docling-serve

# Or if using Docker image:
docker pull ghcr.io/docling-project/docling-serve-cpu:latest
```

**Benefits:**
- Latest features and bug fixes
- Matches internal Docker version
- Better stability

## Current Configuration Summary

```yaml
Network: Docker → host.docker.internal:5001 → Your laptop's Docling
Endpoint: /v1alpha/convert/file (auto-detected)
Status: Network ✅ | API Detection ✅ | Conversion ❌

Fallbacks Available:
1. Internal Extraction Service (port 8010) - Always available
2. Docker Docling (port 5151) - Available if enabled
```

## Testing

### Test External Docling from Docker

```bash
docker exec curatore-backend curl -s \
  http://host.docker.internal:5001/health

# Should return: {"status":"ok"}
```

### Test Conversion from Docker

```bash
docker exec curatore-backend sh -c '
echo "# Test" > /tmp/test.md
curl -X POST "http://host.docker.internal:5001/v1alpha/convert/file" \
  -F "files=@/tmp/test.md" \
  -F "to_formats=md"
'

# Currently returns: "Internal Server Error"
# Check your external Docling logs for details
```

## Next Steps

1. **Check External Docling Logs** - See what's causing the 500 error
2. **Try Restarting External Docling** - May fix stuck state
3. **Test with Different Files** - PDF vs Markdown vs DOCX
4. **Consider Fallback** - Use internal extraction or Docker Docling
5. **Optional:** Upgrade external Docling to v1.9.0+ for better compatibility

## Questions?

If you need help:
1. Share the error logs from your external Docling terminal
2. Confirm which format files you're trying to convert
3. Check if you have enough free memory (2-4GB recommended)
4. Consider whether the internal extraction service meets your needs

Updated: 2026-01-20
