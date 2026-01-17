# Deprecated & Legacy Review (Jobs Framework)

This review catalogs deprecated or legacy elements discovered in the frontend, backend, and documentation after the jobs framework rollout. Each item lists evidence and a recommended migration or cleanup action.

## Review Items

| ID | Area | Element | Evidence | Replacement / Notes | Action |
| --- | --- | --- | --- | --- | --- |
| LEG-API-001 | Backend + Docs | Legacy `/api/*` alias for v1 routes | `backend/app/main.py:499`, `backend/app/main.py:518`, `API_DOCUMENTATION.md:38`, `backend/readme.md:3` | Keep `/api/v1` as canonical; `/api/*` emits deprecation headers. | Plan removal once all clients use `/api/v1`. Update docs to emphasize sunset. |
| JOB-ENDPOINT-001 | Backend + Frontend + Docs | Deprecated single-document processing endpoint `POST /documents/{document_id}/process` | `backend/app/api/v1/routers/documents.py:138`, `frontend/lib/api.ts:192`, `frontend/components/ProcessingPanel.tsx:336`, `API_DOCUMENTATION.md:270`, `backend/readme.md:38`, `README.md:333` | Migrate to `POST /jobs` with `start_immediately` and job tracking. | Replace frontend `processingApi.enqueueDocument` usage and update docs/examples. |
| JOB-ENDPOINT-002 | Backend + Frontend + Docs | Batch processing endpoint `POST /documents/batch/process` (Redis-backed job tracking) | `backend/app/api/v1/routers/documents.py:92`, `frontend/lib/api.ts:207`, `frontend/components/ProcessingPanel.tsx:359`, `API_DOCUMENTATION.md:985`, `backend/readme.md:39`, `README.md:336` | Prefer `POST /jobs` with `document_ids` and DB-backed tracking. | Deprecate endpoint after UI and docs migrate. |
| JOB-TRACKING-001 | Backend | Redis-backed job locks/status cache (legacy job tracking) | `backend/app/services/job_service.py:4`, `backend/app/api/v1/routers/documents.py:193` | Keep only if legacy endpoints remain; DB-backed jobs already exist. | Remove Redis tracking when `/documents/*/process` endpoints are retired. |
| STORAGE-LEGACY-001 | Backend | Legacy flat file structure fallback | `backend/app/services/path_service.py:125`, `backend/app/services/document_service.py:788` | Hierarchical storage should be standard when `use_hierarchical_storage` is enabled. | Decide migration plan, then remove flat fallback. |
| EXTRACT-LEGACY-001 | Backend | Legacy extraction engine aliases (`default`, `extraction`, `legacy`) | `backend/app/services/document_service.py:86`, `backend/app/services/document_service.py:244` | Normalize to `docling` or `extraction-service`. | Remove legacy engine identifiers once clients updated. |
| API-MODEL-LEGACY-001 | Backend | Legacy response alias `is_rag_ready` → `pass_all_thresholds` | `backend/app/api/v1/models.py:663` | Standardize on `pass_all_thresholds`. | Remove alias after frontend and API clients migrate. |
| DOC-CONFIG-LEGACY-001 | Docs | Legacy `.env` configuration references | `README.md:171`, `docs/CONFIGURATION.md:6` | Prefer `config.yml` per current guidance. | Decide whether to retain `.env` support; update docs accordingly. |

## Notes
- The jobs framework is DB-backed; Redis job tracking appears only in legacy endpoints.
- Frontend usage of `processingApi.*` should be audited once `/jobs` routes are fully adopted.
