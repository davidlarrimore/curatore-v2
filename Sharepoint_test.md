# SharePoint Integration Sprint Plan

## Goal
Create a standalone SharePoint ingestion script that authenticates via Microsoft Graph, lists folder contents, downloads files to the Curatore batch directory, and then triggers Docling/extraction to convert files into markdown in processed_files. The script will be segmented for eventual backend integration.

## Sprint 1: Connectivity (implemented)
- Authenticate to Microsoft Graph using app-only credentials.
- Resolve a SharePoint folder URL to a drive item via the Graph shares endpoint.
- Optional: list child items for quick validation.

### Deliverables
- `scripts/sharepoint/sharepoint_connect.py` for connectivity checks.
- Environment variables documented in `.env.example`.

### Setup (venv)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## Sprint 2: Folder Inventory
- Parse a folder URL and list all files with metadata (name, size, created/modified, mime, file extension).
- Support paging across large folders.
- Output a clean, selectable list format (JSON or table).

## Sprint 3: File Selection + Download
- Prompt for single/all file selection.
- Download selected files to `/app/files/batch_files` (or local `./files/batch_files` when running on host).
- Ensure idempotency and checksum/size verification.

## Sprint 4: Docling/Extraction Integration
- Use existing backend/extraction services to convert downloaded files to markdown.
- Store markdown outputs in `/app/files/processed_files`.
- Track per-file conversion status and write a batch summary.

## Sprint 5: Backend Integration
- Wrap logic as a backend service module with a future API endpoint.
- Add minimal tests and a smoke script for CI/local verification.
