# Curatore v2 - API Documentation

**Version**: 2.0.0
**Base URL**: `http://localhost:8000/api/v1` (development)
**Interactive Docs**: http://localhost:8000/docs
**Last Updated**: 2026-01-13

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [API Endpoints](#api-endpoints)
4. [Request/Response Formats](#requestresponse-formats)
5. [Error Handling](#error-handling)
6. [Rate Limiting](#rate-limiting)
7. [Examples](#examples)
8. [SDKs and Client Libraries](#sdks-and-client-libraries)

---

## Overview

Curatore v2 is a comprehensive RAG-ready document processing API that converts documents to markdown, evaluates quality using LLMs, and optimizes content for vector databases.

### Key Features

- **Multi-format Support**: PDF, DOCX, PPTX, TXT, Images (PNG, JPG, etc.)
- **Async Processing**: Redis + Celery for scalable job processing
- **Quality Assessment**: LLM-based evaluation with configurable thresholds
- **Multi-Tenancy**: Organization-based isolation with role-based access control
- **Runtime Configuration**: Dynamic connection management for external services
- **Hierarchical Storage**: Organized file structure with content-based deduplication

### API Versioning

All endpoints are versioned under `/api/v1`. The legacy `/api` prefix is deprecated and will be removed in a future release.

**Current Version**: v1
**Deprecated**: `/api/*` (use `/api/v1/*` instead)

---

## Authentication

Curatore v2 supports two authentication modes based on the `ENABLE_AUTH` environment variable:

### Backward Compatibility Mode (`ENABLE_AUTH=false`)

- **Default behavior**: No authentication required
- **Access**: All endpoints publicly accessible
- **Organization**: Uses `DEFAULT_ORG_ID` from environment
- **Use Case**: Development, single-tenant deployments

### Multi-Tenant Mode (`ENABLE_AUTH=true`)

Authentication is required for all endpoints except health checks and public endpoints.

#### Authentication Methods

##### 1. JWT Tokens (User Authentication)

**Login Flow**:
```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "your-password"
}
```

**Response**:
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "user-uuid",
    "email": "user@example.com",
    "username": "user",
    "role": "admin",
    "organization_id": "org-uuid"
  }
}
```

**Using Access Token**:
```http
GET /api/v1/documents
Authorization: Bearer eyJhbGc...
```

**Token Refresh**:
```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJhbGc..."
}
```

**Token Expiration**:
- Access tokens: 60 minutes (default)
- Refresh tokens: 30 days (default)

##### 2. API Keys (Programmatic Access)

**Creating API Key**:
```http
POST /api/v1/api-keys
Authorization: Bearer eyJhbGc...
Content-Type: application/json

{
  "name": "Production API Key",
  "expires_in_days": 90
}
```

**Response**:
```json
{
  "id": "key-uuid",
  "name": "Production API Key",
  "key": "cur_1234567890abcdef",
  "key_hash": "bcrypt-hash",
  "created_at": "2026-01-13T12:00:00Z",
  "expires_at": "2026-04-13T12:00:00Z",
  "is_active": true,
  "last_used_at": null
}
```

**Important**: The `key` field is only shown once during creation. Store it securely.

**Using API Key**:
```http
GET /api/v1/documents
Authorization: ApiKey cur_1234567890abcdef
```

#### Role-Based Access Control

| Role | Permissions |
|------|-------------|
| `admin` | Full access: manage organization, users, API keys, connections, documents |
| `member` | Document operations, view connections, view users |
| `viewer` | Read-only access to documents and results |

---

## API Endpoints

### System & Health

#### GET `/health`
Basic API health check (no authentication required).

**Response**:
```json
{
  "status": "ok",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

#### GET `/system/health/comprehensive`
Comprehensive health check for all system components.

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-13T12:00:00Z",
  "components": {
    "api": {"status": "healthy", "version": "2.0.0"},
    "database": {"status": "healthy", "type": "postgresql", "connected": true},
    "redis": {"status": "healthy", "connected": true},
    "celery": {"status": "healthy", "workers": 1, "active_tasks": 0},
    "extraction": {"status": "healthy", "url": "http://extraction:8010"},
    "llm": {"status": "healthy", "available": true},
    "sharepoint": {"status": "unavailable", "error": "No connection configured"}
  }
}
```

#### GET `/system/queues`
Get queue health and metrics.

**Response**:
```json
{
  "queue_health": {
    "redis_connected": true,
    "celery_workers": 1
  },
  "jobs": {
    "total": 5,
    "by_status": {
      "PENDING": 2,
      "STARTED": 1,
      "SUCCESS": 2,
      "FAILURE": 0
    }
  }
}
```

#### GET `/config/supported-formats`
Get list of supported file formats.

**Response**:
```json
{
  "formats": [
    {
      "extension": ".pdf",
      "mime_type": "application/pdf",
      "description": "PDF documents",
      "max_size_mb": 50
    },
    {
      "extension": ".docx",
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "description": "Word documents",
      "max_size_mb": 50
    }
  ]
}
```

---

### Documents

#### POST `/documents/upload`
Upload a document for processing.

**Request**:
```http
POST /api/v1/documents/upload
Authorization: Bearer eyJhbGc...
Content-Type: multipart/form-data

file: (binary data)
```

**Response**:
```json
{
  "document_id": "doc-uuid",
  "filename": "report.pdf",
  "size_bytes": 1048576,
  "uploaded_at": "2026-01-13T12:00:00Z",
  "status": "uploaded"
}
```

**Error Responses**:
- `400 Bad Request`: Invalid file format or size
- `401 Unauthorized`: Missing or invalid authentication
- `413 Payload Too Large`: File exceeds maximum size

#### POST `/documents/{document_id}/process`
Enqueue a single document for asynchronous processing.

**Deprecated**: Use `POST /jobs` with `document_ids` instead. This endpoint remains for backward compatibility but will be removed in a future release.

**Request**:
```http
POST /api/v1/documents/{document_id}/process
Authorization: Bearer eyJhbGc...
Content-Type: application/json

{
  "optimize_for_rag": true,
  "evaluate_quality": true,
  "quality_thresholds": {
    "conversion_threshold": 70,
    "clarity_threshold": 7,
    "completeness_threshold": 7
  }
}
```

**Response**:
```json
{
  "job_id": "job-uuid",
  "document_id": "doc-uuid",
  "status": "PENDING",
  "enqueued_at": "2026-01-13T12:00:00Z"
}
```

**Error Responses**:
- `404 Not Found`: Document not found
- `409 Conflict`: Document is already being processed

#### GET `/documents/{document_id}/result`
Get processing result for a document.

**Response**:
```json
{
  "document_id": "doc-uuid",
  "filename": "report.pdf",
  "status": "completed",
  "conversion": {
    "success": true,
    "engine": "default",
    "quality_score": 85,
    "markdown_length": 12450,
    "processing_time_seconds": 3.2
  },
  "evaluation": {
    "clarity_score": 8,
    "completeness_score": 9,
    "relevance_score": 8,
    "markdown_quality_score": 9,
    "overall_quality": 85,
    "recommendations": ["Content is well-structured and suitable for RAG"]
  },
  "optimization": {
    "performed": true,
    "changes": ["Added section headers", "Improved table formatting"]
  },
  "metadata": {
    "page_count": 15,
    "word_count": 2500,
    "has_images": true,
    "has_tables": true
  }
}
```

#### GET `/documents/{document_id}/content`
Get raw markdown content.

**Response**:
```markdown
# Report Title

## Executive Summary

This is the extracted markdown content...
```

#### GET `/documents/{document_id}/download`
Download markdown file.

**Response**: File download with `Content-Disposition: attachment`

---

### Jobs

#### POST `/jobs`
Create a new batch job for one or more documents.

**Request**:
```json
{
  "document_ids": ["doc-123", "doc-456"],
  "options": {
    "apply_llm_evaluation": true,
    "quality_thresholds": {
      "conversion_threshold": 70,
      "clarity_threshold": 7
    }
  },
  "name": "Q1 Report Processing",
  "start_immediately": true
}
```

**Response**:
```json
{
  "id": "job-uuid",
  "name": "Q1 Report Processing",
  "status": "QUEUED",
  "total_documents": 2,
  "created_at": "2026-01-13T12:00:00Z",
  "queued_at": "2026-01-13T12:00:01Z"
}
```

#### GET `/jobs/{job_id}`
Get job status and details.

**Response**:
```json
{
  "id": "job-uuid",
  "name": "Q1 Report Processing",
  "status": "RUNNING",
  "total_documents": 2,
  "completed_documents": 1,
  "failed_documents": 0,
  "created_at": "2026-01-13T12:00:00Z",
  "started_at": "2026-01-13T12:00:05Z",
  "documents": [
    {"document_id": "doc-123", "filename": "report.pdf", "status": "COMPLETED"},
    {"document_id": "doc-456", "filename": "summary.pdf", "status": "RUNNING"}
  ],
  "recent_logs": [
    {"timestamp": "2026-01-13T12:00:06Z", "level": "INFO", "message": "Document processing started: doc-123"}
  ]
}
```

**Job Status Values**:
- `PENDING`: Created, not yet queued
- `QUEUED`: Tasks enqueued, waiting for workers
- `RUNNING`: At least one document is processing
- `COMPLETED`: All documents completed successfully
- `FAILED`: One or more documents failed
- `CANCELLED`: Job cancelled

**Document Status Values**:
- `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`

---

### Authentication (Multi-Tenant Mode)

#### POST `/auth/register`
Register a new user account.

**Request**:
```json
{
  "email": "newuser@example.com",
  "username": "newuser",
  "password": "SecurePassword123!",
  "full_name": "New User",
  "organization_id": "org-uuid"
}
```

**Response**:
```json
{
  "id": "user-uuid",
  "email": "newuser@example.com",
  "username": "newuser",
  "full_name": "New User",
  "role": "member",
  "organization_id": "org-uuid",
  "created_at": "2026-01-13T12:00:00Z",
  "email_verified": false
}
```

#### POST `/auth/verify-email`
Verify email address with token.

**Request**:
```json
{
  "token": "verification-token-from-email"
}
```

**Response**:
```json
{
  "message": "Email verified successfully",
  "user": {
    "id": "user-uuid",
    "email_verified": true
  }
}
```

#### POST `/auth/request-password-reset`
Request password reset email.

**Request**:
```json
{
  "email": "user@example.com"
}
```

**Response**:
```json
{
  "message": "If the email exists, a password reset link has been sent"
}
```

#### POST `/auth/reset-password`
Reset password with token.

**Request**:
```json
{
  "token": "reset-token-from-email",
  "new_password": "NewSecurePassword123!"
}
```

---

### Connections (Multi-Tenant Mode)

#### GET `/connections`
List all connections for the organization.

**Response**:
```json
{
  "connections": [
    {
      "id": "conn-uuid",
      "name": "Production SharePoint",
      "type": "sharepoint",
      "is_active": true,
      "is_default": true,
      "last_tested_at": "2026-01-13T12:00:00Z",
      "health_status": "healthy",
      "created_at": "2026-01-01T12:00:00Z"
    }
  ],
  "total": 1
}
```

#### POST `/connections`
Create a new connection.

**Request (SharePoint)**:
```json
{
  "name": "Production SharePoint",
  "type": "sharepoint",
  "config": {
    "tenant_id": "tenant-guid",
    "client_id": "client-guid",
    "client_secret": "secret-value",
    "site_url": "https://tenant.sharepoint.com/sites/docs"
  },
  "is_default": true,
  "auto_test": true
}
```

**Request (LLM)**:
```json
{
  "name": "OpenAI GPT-4",
  "type": "openai",
  "config": {
    "api_key": "sk-...",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "timeout": 30
  },
  "is_default": true
}
```

**Response**:
```json
{
  "id": "conn-uuid",
  "name": "Production SharePoint",
  "type": "sharepoint",
  "is_active": true,
  "is_default": true,
  "health_status": "healthy",
  "test_result": {
    "success": true,
    "status": "healthy",
    "message": "Connection successful"
  }
}
```

#### POST `/connections/{connection_id}/test`
Test connection health.

**Response**:
```json
{
  "success": true,
  "status": "healthy",
  "message": "SharePoint connection successful",
  "details": {
    "site_title": "Documents Site",
    "response_time_ms": 245
  },
  "tested_at": "2026-01-13T12:00:00Z"
}
```

---

### SharePoint Integration

#### POST `/sharepoint/inventory`
List files in a SharePoint folder.

**Request**:
```json
{
  "folder_url": "https://tenant.sharepoint.com/sites/docs/Shared Documents/Reports",
  "recursive": false,
  "include_folders": false,
  "page_size": 200
}
```

**Response**:
```json
{
  "total_files": 15,
  "total_folders": 3,
  "files": [
    {
      "index": 1,
      "name": "Q4_Report.pdf",
      "type": "pdf",
      "size_bytes": 1048576,
      "size_mb": 1.0,
      "modified": "2026-01-10T12:00:00Z",
      "path": "/sites/docs/Shared Documents/Reports/Q4_Report.pdf",
      "web_url": "https://..."
    }
  ],
  "folders": [
    {
      "index": 1,
      "name": "Archive",
      "path": "/sites/docs/Shared Documents/Reports/Archive",
      "web_url": "https://..."
    }
  ]
}
```

#### POST `/sharepoint/download`
Download selected files to batch directory.

**Request**:
```json
{
  "folder_url": "https://tenant.sharepoint.com/sites/docs/Shared Documents/Reports",
  "indices": [1, 3, 5],
  "preserve_folders": true
}
```

**Response**:
```json
{
  "downloaded_files": 3,
  "skipped_files": 0,
  "total_size_bytes": 3145728,
  "files": [
    {
      "name": "Q4_Report.pdf",
      "local_path": "/app/files/batch_files/Q4_Report.pdf",
      "size_bytes": 1048576
    }
  ],
  "download_duration_seconds": 2.5
}
```

---

### Storage Management

#### GET `/storage/stats`
Get storage statistics.

**Response**:
```json
{
  "organizations": {
    "org-uuid": {
      "total_files": 150,
      "total_size_bytes": 104857600,
      "batches": 5,
      "adhoc_files": 20
    }
  },
  "dedupe": {
    "unique_files": 100,
    "total_references": 150,
    "space_saved_bytes": 52428800,
    "space_saved_mb": 50.0,
    "deduplication_ratio": 0.33
  },
  "temp": {
    "jobs": 2,
    "total_size_bytes": 2097152
  }
}
```

#### POST `/storage/cleanup`
Trigger manual cleanup of expired files.

**Response**:
```json
{
  "files_deleted": 25,
  "space_freed_bytes": 26214400,
  "duration_seconds": 1.2
}
```

#### GET `/storage/duplicates`
List duplicate files detected by content hash.

**Response**:
```json
{
  "duplicates": [
    {
      "hash": "sha256-hash",
      "file_count": 3,
      "size_bytes": 1048576,
      "space_saved_bytes": 2097152,
      "files": [
        {
          "path": "/org-1/batch-1/report.pdf",
          "uploaded_at": "2026-01-10T12:00:00Z"
        },
        {
          "path": "/org-1/batch-2/report.pdf",
          "uploaded_at": "2026-01-11T12:00:00Z"
        }
      ]
    }
  ],
  "total_duplicates": 1,
  "total_space_saved_bytes": 2097152
}
```

---

## Request/Response Formats

### Content Types

**Supported Request Content Types**:
- `application/json` - JSON request bodies
- `multipart/form-data` - File uploads

**Response Content Types**:
- `application/json` - Standard API responses
- `text/markdown` - Markdown content
- `application/octet-stream` - File downloads

### Common Request Headers

```http
Authorization: Bearer {access_token}
Content-Type: application/json
Accept: application/json
X-Request-ID: {optional-request-id}
```

### Common Response Headers

```http
Content-Type: application/json
X-Request-ID: {request-id}
X-Process-Time: {duration-ms}ms
```

### Pagination

For list endpoints that support pagination:

**Request**:
```http
GET /api/v1/documents?limit=20&offset=40
```

**Response**:
```json
{
  "items": [...],
  "total": 150,
  "limit": 20,
  "offset": 40,
  "has_more": true
}
```

---

## Error Handling

### Error Response Format

All errors follow a consistent format:

```json
{
  "error": "Error Type",
  "detail": "Detailed error message",
  "timestamp": "2026-01-13T12:00:00Z",
  "request_id": "req-uuid"
}
```

### HTTP Status Codes

| Code | Meaning | Usage |
|------|---------|-------|
| `200` | OK | Successful request |
| `201` | Created | Resource created successfully |
| `400` | Bad Request | Invalid request format or parameters |
| `401` | Unauthorized | Missing or invalid authentication |
| `403` | Forbidden | Insufficient permissions |
| `404` | Not Found | Resource not found |
| `409` | Conflict | Resource conflict (e.g., duplicate processing) |
| `413` | Payload Too Large | File size exceeds limit |
| `422` | Unprocessable Entity | Validation error |
| `429` | Too Many Requests | Rate limit exceeded |
| `500` | Internal Server Error | Server error |
| `503` | Service Unavailable | Service temporarily unavailable |

### Common Error Scenarios

#### Authentication Errors

**Missing Token**:
```json
{
  "error": "HTTP 401",
  "detail": "Not authenticated",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

**Expired Token**:
```json
{
  "error": "HTTP 401",
  "detail": "Token has expired",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

**Invalid API Key**:
```json
{
  "error": "HTTP 401",
  "detail": "Invalid API key",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

#### Validation Errors

```json
{
  "error": "Validation Error",
  "detail": "field required: email",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

#### Resource Conflicts

```json
{
  "error": "HTTP 409",
  "detail": "Document is already being processed by job: job-uuid",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

---

## Rate Limiting

### Current Limits

**Default Limits** (when `ENABLE_AUTH=true`):
- **Per User**: 1000 requests per hour
- **Per API Key**: 5000 requests per hour
- **File Upload**: 100 uploads per hour

**Headers**:
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 945
X-RateLimit-Reset: 1705154400
```

### Handling Rate Limits

When rate limited, you'll receive a `429 Too Many Requests` response:

```json
{
  "error": "HTTP 429",
  "detail": "Rate limit exceeded. Try again in 3600 seconds.",
  "timestamp": "2026-01-13T12:00:00Z"
}
```

**Best Practices**:
- Implement exponential backoff
- Monitor `X-RateLimit-Remaining` header
- Use batch operations when possible
- Cache results when appropriate

---

## Examples

### Complete Document Processing Workflow

```python
import requests
import time

# Configuration
API_BASE = "http://localhost:8000/api/v1"
API_KEY = "cur_1234567890abcdef"
headers = {"Authorization": f"ApiKey {API_KEY}"}

# 1. Upload document
with open("report.pdf", "rb") as f:
    response = requests.post(
        f"{API_BASE}/documents/upload",
        headers=headers,
        files={"file": f}
    )
document_id = response.json()["document_id"]
print(f"Uploaded: {document_id}")

# 2. Start processing (jobs framework)
response = requests.post(
    f"{API_BASE}/jobs",
    headers=headers,
    json={
        "document_ids": [document_id],
        "options": {
            "optimize_for_rag": True,
            "evaluate_quality": True
        },
        "start_immediately": True
    }
)
job_id = response.json()["id"]
print(f"Processing job: {job_id}")

# 3. Poll for completion
while True:
    response = requests.get(
        f"{API_BASE}/jobs/{job_id}",
        headers=headers
    )
    status = response.json()["status"]
    print(f"Status: {status}")

    if status in ["COMPLETED", "FAILED", "CANCELLED"]:
        break

    time.sleep(2)

# 4. Get result
if status == "COMPLETED":
    response = requests.get(
        f"{API_BASE}/documents/{document_id}/result",
        headers=headers
    )
    result = response.json()
    print(f"Quality: {result['evaluation']['overall_quality']}")

    # 5. Download markdown
    response = requests.get(
        f"{API_BASE}/documents/{document_id}/download",
        headers=headers
    )
    with open("report.md", "wb") as f:
        f.write(response.content)
    print("Downloaded markdown")
```

### SharePoint Integration Workflow

```python
# 1. List SharePoint files
response = requests.post(
    f"{API_BASE}/sharepoint/inventory",
    headers=headers,
    json={
        "folder_url": "https://tenant.sharepoint.com/sites/docs/Shared Documents",
        "recursive": False
    }
)
files = response.json()["files"]
print(f"Found {len(files)} files")

# 2. Download selected files
indices = [1, 2, 3]  # Select first 3 files
response = requests.post(
    f"{API_BASE}/sharepoint/download",
    headers=headers,
    json={
        "folder_url": "https://tenant.sharepoint.com/sites/docs/Shared Documents",
        "indices": indices
    }
)
print(f"Downloaded {response.json()['downloaded_files']} files")

# 3. Create a processing job for downloaded documents
batch_files = requests.get(
    f"{API_BASE}/documents/batch",
    headers=headers
).json()["files"]
document_ids = [f["document_id"] for f in batch_files]

response = requests.post(
    f"{API_BASE}/jobs",
    headers=headers,
    json={"document_ids": document_ids, "start_immediately": True}
)
job_id = response.json()["id"]
print(f"Processing job: {job_id}")
```

### Connection Management

```python
# Create LLM connection
response = requests.post(
    f"{API_BASE}/connections",
    headers=headers,
    json={
        "name": "OpenAI GPT-4",
        "type": "openai",
        "config": {
            "api_key": "sk-...",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1"
        },
        "is_default": True,
        "auto_test": True
    }
)
connection_id = response.json()["id"]
print(f"Created connection: {connection_id}")

# Test connection
response = requests.post(
    f"{API_BASE}/connections/{connection_id}/test",
    headers=headers
)
health = response.json()
print(f"Health: {health['status']}")
```

---

## SDKs and Client Libraries

### Python SDK (Coming Soon)

```python
from curatore import Client

client = Client(
    api_key="cur_1234567890abcdef",
    base_url="http://localhost:8000"
)

# Upload and process
document = client.documents.upload("report.pdf")
job = document.process(optimize_for_rag=True)
job.wait()

if job.status == "SUCCESS":
    result = document.get_result()
    print(f"Quality: {result.quality_score}")
    document.download("report.md")
```

### JavaScript/TypeScript SDK (Coming Soon)

```typescript
import { CuratoreClient } from '@curatore/sdk';

const client = new CuratoreClient({
  apiKey: 'cur_1234567890abcdef',
  baseUrl: 'http://localhost:8000'
});

// Upload and process
const document = await client.documents.upload('report.pdf');
const job = await document.process({ optimizeForRag: true });
await job.wait();

if (job.status === 'SUCCESS') {
  const result = await document.getResult();
  console.log(`Quality: ${result.qualityScore}`);
  await document.download('report.md');
}
```

---

## Support and Resources

### Documentation
- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **User Guide**: [USER_GUIDE.md](USER_GUIDE.md)
- **Deployment Guide**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

### Getting Help
- **GitHub Issues**: Report bugs and feature requests
- **Email Support**: support@curatore.io (production deployments)
- **Status Page**: https://status.curatore.io

### Additional Resources
- **Architecture**: [plan.md](plan.md)
- **Development Guide**: [CLAUDE.md](CLAUDE.md)
- **Testing Guide**: [backend/tests/README_TESTS.md](backend/tests/README_TESTS.md)

---

**Last Updated**: 2026-01-13
**API Version**: 2.0.0
**Documentation Version**: 1.0.0
