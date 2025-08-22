# Backend (FastAPI)

## Endpoints
- `GET /healthz` – app + LLM probe
- `GET /settings` – current defaults for UI forms
- `GET /files` – list uploaded files
- `POST /files:upload` – upload one file (multipart)
- `DELETE /files` – delete all uploaded files
- `POST /jobs` – create & run job for selected filenames
- `GET /jobs/{id}` – job status/results/logs

## Local dev
```bash
uvicorn curatore_api.main:app --reload