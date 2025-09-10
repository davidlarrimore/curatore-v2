# Backend (FastAPI)

Curatore’s backend provides a single, stable REST API at `/api/v1`. A legacy alias `/api/*` maps to v1 and returns deprecation headers.

## Overview
- Framework: FastAPI
- Async jobs: Celery + Redis
- Storage: Local filesystem for files; in‑memory store for results (with Redis keys for job metadata)
- Docs: Swagger UI at `/api/v1/docs`, OpenAPI JSON at `/openapi-v1.json`

## API Layout
```
app/
├── api/
│   └── v1/
│       └── routers/
│           ├── documents.py   # Upload/list/process/download
│           ├── jobs.py        # Job status endpoints
│           └── system.py      # Health, config, queues
├── services/
│   ├── document_service.py    # Processing pipeline
│   ├── llm_service.py         # LLM integration
│   ├── storage_service.py     # Result storage
│   └── zip_service.py         # Archive creation
├── models.py                  # Pydantic models
├── config.py                  # Settings (env‑driven)
└── main.py                    # FastAPI app setup
```

## Common Endpoints (v1)
- System/health: `GET /api/v1/health`
- Supported formats: `GET /api/v1/config/supported-formats`
- Defaults/config: `GET /api/v1/config/defaults`
- Extraction services: `GET /api/v1/config/extraction-services` (lists available extractors and which is active)
- List uploaded files: `GET /api/v1/documents/uploaded`
- List batch files: `GET /api/v1/documents/batch`
- Upload file: `POST /api/v1/documents/upload` (multipart)
- Enqueue processing: `POST /api/v1/documents/{document_id}/process`
- Batch enqueue: `POST /api/v1/documents/batch/process`
- Job status: `GET /api/v1/jobs/{job_id}`
- Latest job by document: `GET /api/v1/jobs/by-document/{document_id}`
- Result payload: `GET /api/v1/documents/{document_id}/result`
- Content (markdown): `GET /api/v1/documents/{document_id}/content`
- Download md: `GET /api/v1/documents/{document_id}/download`
- Bulk download: `POST /api/v1/documents/download/bulk`
- RAG‑ready zip: `GET /api/v1/documents/download/rag-ready`
- Queue health: `GET /api/v1/system/queues`
- Queue summary: `GET /api/v1/system/queues/summary?batch_id=...` or `?job_ids=...`

## Local Development
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Testing
```bash
cd backend
pip install -r requirements.txt
pytest -q
```

## Quick Smoke Checks
```bash
curl -s localhost:8000/api/v1/health | jq
open http://localhost:8000/api/v1/docs
curl -s localhost:8000/api/v1/system/queues | jq
curl -s "localhost:8000/api/v1/system/queues/summary?job_ids=a,b,c" | jq
```
