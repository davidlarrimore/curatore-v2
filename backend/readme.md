# Backend (FastAPI)

This backend uses path-based API versioning with separate packages per version. Stable clients should target explicit versions like `/api/v1` or `/api/v2`. A temporary legacy alias `/api/*` maps to v1 and returns deprecation headers.

## Versioning Strategy
- Preferred paths: `/api/v1/*`, `/api/v2/*`
- Legacy alias: `/api/*` → v1 (responds with `Deprecation: true`, `Sunset`, `Link` headers)
- Versioned docs: `/docs/v1`, `/docs/v2` (plus combined `/docs`)
- Versioned OpenAPI: `/openapi-v1.json`, `/openapi-v2.json`

## Project Layout (API)
- `backend/app/api/v1` – v1 package
  - `__init__.py` – assembles v1 routers into `api_router`
  - `models.py` – version-scoped exports of domain models
  - `routers/` – v1 routers (e.g., `system.py`, `documents.py`)
- `backend/app/api/v2` – v2 package (baseline copies of v1)
  - `__init__.py` – assembles v2 routers into `api_router`
  - `models.py` – version-scoped exports of domain models
  - `routers/` – v2 routers (baseline to evolve from)
- `backend/app/main.py` – mounts `/api/v1`, `/api/v2`, `/api` and customizes OpenAPI

Domain models used across versions live in `backend/app/models.py`. Each version’s `models.py` re-exports specific schemas to provide a stable import surface that can diverge later.

## Create a New Version (e.g., v3)
1) Create the package
```bash
mkdir -p backend/app/api/v3/routers
```

2) Add `backend/app/api/v3/__init__.py`
```python
from fastapi import APIRouter
from .routers import documents, system  # add other routers as needed

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(system.router)
```

3) Add `backend/app/api/v3/models.py`
```python
from ...models import (
    FileUploadResponse,
    ProcessingResult,
    BatchProcessingRequest,
    BatchProcessingResult,
    DocumentEditRequest,
    ProcessingOptions,
    BulkDownloadRequest,
    ZipArchiveInfo,
    HealthStatus,
    LLMConnectionStatus,
)
```

4) Copy routers from the previous stable version (v2 → v3)
- Copy `backend/app/api/v2/routers/*` to `backend/app/api/v3/routers/`
- Update imports inside routers to point to `..models` (v3) and keep relative imports to services/config

5) Mount the new version in `backend/app/main.py`
```python
from .api.v3 import api_router as v3_router
app.include_router(v3_router, prefix="/api/v3")
```

6) (Optional) Extend per-version docs
- `/openapi-v3.json` and `/docs/v3` can be added following the existing v1/v2 pattern in `main.py`

## How To Evolve V2 (Baseline)
- Modify only files under `backend/app/api/v2/*`
- If schemas change, edit `backend/app/api/v2/models.py` (avoid changing shared `app/models.py` unless changes apply to all versions)
- If endpoints change, update `backend/app/api/v2/routers/*.py`

## Testing
### Run unit tests
```bash
cd backend
pip install -r requirements.txt
pytest -q
```

### Quick smoke tests
```bash
# Health checks
curl -s localhost:8000/api/v1/health | jq
curl -s localhost:8000/api/v2/health | jq

# Legacy alias (returns Deprecation headers)
curl -i -s localhost:8000/api/health | head -n 20

# OpenAPI docs
open http://localhost:8000/docs
open http://localhost:8000/docs/v1
open http://localhost:8000/docs/v2
```

### Dev server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
