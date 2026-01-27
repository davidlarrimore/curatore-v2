# SAM.gov Scripts Migration Guide

⚠️  **IMPORTANT - TEMPORARY SOLUTION**

This migration guide documents a **TEMPORARY** approach for SAM.gov scripts to use
the backend API. The entire SAM.gov external script system (including this guide,
backend_upload.py, and the proxy endpoints) will be **REMOVED** when native SAM.gov
integration is built into the Curatore backend/frontend.

**DO NOT** build new features on top of this temporary infrastructure.

---

## Overview

The SAM.gov scripts previously uploaded files directly to MinIO with custom document IDs (e.g., `sam_70ABC123_file.pdf`). This approach bypassed the backend API and created non-standard document identifiers.

**Current Approach**: Hybrid upload strategy
- **Consolidated JSON & Summary Reports**: Upload via backend API to get proper UUID document IDs
- **Resource Files**: Upload directly to MinIO with custom folder structure organized by solicitation number

This maintains the user-expected file organization for SAM resource files while ensuring main data files (JSON, summaries) get proper UUIDs.

**Future Approach**: Native SAM.gov integration in the backend/frontend will replace these external scripts entirely.

## Why Migrate?

1. **Standard UUIDs**: All documents now use UUID format for consistency
2. **Proper Tracking**: Backend API creates artifact records automatically
3. **API Integration**: Scripts are proper API clients, not bypassing the backend
4. **Security**: API handles auth, validation, and access control
5. **Maintainability**: Changes to storage logic don't break scripts

## Migration Steps

### Step 1: Use Backend Upload Helper

Instead of directly calling `minio_client.put_object()`, use the new `backend_upload.py` helper:

**Before (Direct MinIO)**:
```python
from minio import Minio

# Old approach - DEPRECATED
minio_client = Minio(...)
key = f"{org_id}/sam/{solicitation}/{filename}"
document_id = f"sam_{solicitation}_{filename}"  # Custom ID

result = minio_client.put_object(
    bucket_name="curatore-uploads",
    object_name=key,
    data=file_stream,
    length=file_size,
    content_type=content_type,
)
```

**After (Backend API)**:
```python
from backend_upload import upload_file_to_backend

# New approach - RECOMMENDED
document_id = upload_file_to_backend(
    file_content=file_bytes,
    filename=filename,
    content_type=content_type,
    metadata={
        "source": "sam.gov",
        "solicitation_number": solicitation,
        "notice_id": notice_id,
    },
    api_url="http://localhost:8000",
    api_key=os.getenv("API_KEY")  # Optional
)

# document_id is now a proper UUID like "550e8400-e29b-41d4-a716-446655440000"
print(f"Uploaded with UUID: {document_id}")
```

### Step 2: Update Database Tracking

If you're tracking document IDs in your own database or logs, update them to store UUIDs:

**Before**:
```python
# Custom document ID
doc_id = f"sam_{solicitation}_{filename}"
# Store in database/log...
```

**After**:
```python
# UUID from backend
doc_id = upload_file_to_backend(...)
# Store UUID in database/log...
```

### Step 3: Update File Organization (Optional)

The backend API uses a standardized folder structure:
- Upload: `{org_id}/{document_id}/uploaded/{filename}`
- Processed: `{org_id}/{document_id}/processed/{filename}.md`

You don't need to specify paths - the backend handles this automatically. However, you can still use metadata to track your custom organization:

```python
document_id = upload_file_to_backend(
    file_content=file_bytes,
    filename=filename,
    content_type=content_type,
    metadata={
        "source": "sam.gov",
        "solicitation_number": solicitation,  # Your custom tracking
        "folder_path": f"sam/{solicitation}",  # Your custom path (for reference)
        "original_key": key,  # Original MinIO key (for reference)
    }
)
```

### Step 4: Environment Variables

Add API authentication (if `ENABLE_AUTH=true`):

```bash
# .env file
ENABLE_AUTH=true
API_KEY=your-api-key-here  # Generate via frontend or CLI
```

Generate API key:
```bash
# Via CLI (when ENABLE_AUTH=true)
python -m app.commands.create_api_key --user-email admin@example.com --name "SAM.gov Scripts"

# Or via frontend:
# Navigate to Settings > API Keys > Create New Key
```

### Step 5: Update Error Handling

The backend API returns structured errors:

```python
import requests

try:
    doc_id = upload_file_to_backend(...)
    print(f"✓ Uploaded: {doc_id}")
except requests.HTTPError as e:
    print(f"✗ Upload failed: {e.response.status_code}")
    print(f"  Error: {e.response.json().get('detail', 'Unknown error')}")
except KeyError as e:
    print(f"✗ Response missing document_id: {e}")
```

## Example: Migrating sam_pull.py

Here's how to migrate the resource file download section:

**Before (Lines 548-577)**:
```python
# Old code with custom document ID
key = f"{DEFAULT_ORG_ID}/sam/{solicitation_number}/{filename}"
document_id = f"sam_{solicitation_number}_{filename}"

file_bytes = response.content
file_stream = BytesIO(file_bytes)
file_size = len(file_bytes)

result = minio_client.put_object(
    bucket_name=bucket,
    object_name=key,
    data=file_stream,
    length=file_size,
    content_type=content_type,
    metadata={
        "source": "sam.gov",
        "notice_id": notice_id,
        "solicitation_number": solicitation_number,
    }
)

# Track in database with custom ID
artifact_service.create_artifact(
    document_id=document_id,  # Custom ID
    ...
)
```

**After**:
```python
from backend_upload import upload_file_to_backend

# New code with UUID from backend
file_bytes = response.content

document_id = upload_file_to_backend(
    file_content=file_bytes,
    filename=filename,
    content_type=content_type,
    metadata={
        "source": "sam.gov",
        "notice_id": notice_id,
        "solicitation_number": solicitation_number,
        "link_name": link_name,
    },
    api_url=os.getenv("API_URL", "http://localhost:8000"),
    api_key=os.getenv("API_KEY")  # Optional if ENABLE_AUTH=false
)

# document_id is now a proper UUID
# Backend automatically creates artifact record - no manual tracking needed!
print(f"✓ Uploaded {filename}: {document_id}")
```

## Benefits After Migration

1. **UUIDs Everywhere**: Consistent document IDs across all sources
2. **Simplified Code**: No manual artifact tracking needed
3. **API-First**: Scripts are proper API clients
4. **Future-Proof**: Backend changes don't break scripts
5. **Better Errors**: Structured error messages from API
6. **Authentication**: Support for API keys when needed

## Testing Migration

1. **Test Upload**:
   ```bash
   python -c "from backend_upload import upload_file_to_backend; print(upload_file_to_backend(b'test', 'test.txt'))"
   ```

2. **Verify in Frontend**:
   - Navigate to http://localhost:3000/storage
   - Check that file appears with UUID document ID
   - Verify metadata is preserved

3. **Test Processing**:
   - Create a job with uploaded files
   - Verify processing works with UUID document IDs

## Rollback Plan

If you need to rollback:
1. Keep old scripts as backup
2. MinIO files remain untouched
3. Only new uploads use UUIDs
4. Old custom IDs in database won't work with new validators

**Recommendation**: Re-upload important files through the backend API to get proper UUIDs.

## Need Help?

- Check API documentation: http://localhost:8000/docs
- Test upload endpoint: `POST /api/v1/storage/upload/proxy`
- Review `backend_upload.py` helper functions
- Check backend logs: `docker-compose logs backend`

---

## Future: Native SAM.gov Integration

**This entire external script system is TEMPORARY and will be replaced.**

When native SAM.gov integration is built into the Curatore backend/frontend, the following will be removed:

### Files to Remove:
1. `/scripts/sam/backend_upload.py` - Helper module
2. `/scripts/sam/sam_pull.py` - External pull script
3. `/scripts/sam/MIGRATION_GUIDE.md` - This guide
4. `/backend/app/api/v1/routers/storage.py`:
   - `POST /upload/proxy` endpoint
   - `GET /download/{document_id}/proxy` endpoint
   - `GET /object/download` proxy endpoint

### Replacement Features:
1. **Backend API Endpoints**:
   - `POST /api/v1/sam/sync` - Sync opportunities from SAM.gov API
   - `GET /api/v1/sam/opportunities` - List synced opportunities
   - `POST /api/v1/sam/opportunities/{id}/import` - Import specific opportunity files
   - `GET /api/v1/sam/config` - SAM.gov connection configuration

2. **Frontend Pages**:
   - `/sam` - SAM.gov opportunity browser
   - `/sam/settings` - Connection and sync configuration
   - `/sam/opportunities/{id}` - Opportunity detail with file import

3. **Native Workflows**:
   - Scheduled background sync (cron job)
   - Real-time opportunity monitoring
   - One-click file import with automatic processing
   - Integrated metadata and tracking
   - Notification system for new opportunities

### Migration Path (When Native Integration is Ready):
1. Export existing SAM.gov document IDs and metadata
2. Re-import through native SAM integration if needed
3. Update documentation to reference native workflows
4. Remove all external scripts and proxy endpoints
5. Archive this migration guide for historical reference

**Timeline**: To be determined based on feature prioritization.
