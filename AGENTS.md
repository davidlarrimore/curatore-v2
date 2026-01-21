# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI API service. Core code in `backend/app`, tests in `backend/tests`.
- `frontend/`: Next.js app. App Router pages in `frontend/app`, shared UI in `frontend/components`, styles in `frontend/styles`, assets in `frontend/public`.
- `extraction-service/`: Standalone FastAPI conversion service with `extraction-service/app` and `extraction-service/tests`.
- `scripts/`: Dev and test helpers (e.g., `dev-up.sh`, `run_all_tests.sh`).
- `data/`, `files/`, `logs/`: runtime artifacts and local storage.

## Build, Test, and Development Commands
- `./scripts/dev-up.sh` or `make up`: start backend, worker, frontend, redis, and extraction services with Docker Compose.
- `make down`: stop all services and remove orphans.
- `cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`: run the backend locally with hot reload.
- `cd frontend && npm install && npm run dev`: install dependencies and start the Next.js dev server.
- `npm run type-check` / `npm run lint`: run TypeScript checks and ESLint for the frontend.
- `./scripts/run_all_tests.sh`: run the full test suite.

## Coding Style & Naming Conventions
- Python follows PEP 8 conventions (4-space indentation, `snake_case` for functions and modules).
- TypeScript/React uses 2-space indentation with `PascalCase` component names and `camelCase` functions.
- Prefer descriptive names for APIs, routes, and components that match domain concepts (e.g., `DocumentBatch`, `ProcessingPanel`).
- Use `npm run lint` and `npm run type-check` before submitting frontend changes.

## Frontend UI/UX Consistency
- Base theme is light: use `bg-slate-50`/`bg-white` surfaces with `text-slate-800`/`text-slate-900` and `border-slate-200`.
- Primary actions use blue (`blue-600` with `hover:blue-700`); statuses use `green-600`, `yellow-500/600`, `red-600`, and info/accents use `indigo-600`/`purple-600` gradients sparingly (e.g., progress steps).
- Prefer shared UI primitives in `frontend/components/ui` (`Button`, `Badge`, `Accordion`, `ProgressBar`) over bespoke markup.
- Use global utility classes in `frontend/styles/globals.css` for common patterns: `card`, `card-header`, `card-content`, `metric-card`, `status-*`, `processing-item`, `upload-zone`, `drop-zone`, `file-item`, `file-list`, `data-table`, `loading-*`, `scrollbar-thin`, `focus-ring`.
- Layout spacing favors `rounded-lg`/`rounded-xl`, `shadow-sm` with `hover:shadow-md`, and `transition-colors`/`transition-all` for interactive elements.
- Typography hierarchy: `text-sm` for body, `text-xs` for metadata, `font-medium` labels, and muted text in `text-slate-500`/`text-slate-600`.
- Form controls rely on base styles in `globals.css`; avoid custom input styling unless necessary.

## Testing Guidelines
- Backend and extraction service tests use `pytest`; name tests `test_*.py` and keep them near the service they cover.
- Run backend tests with `pytest backend/tests` and extraction tests with `pytest extraction-service/tests -v`.
- Use `./scripts/api_smoke_test.sh` and `./scripts/queue_health.sh` for quick runtime checks.

## Configuration Consistency Checklist
- When updating extraction connection settings, verify alignment across:
  - `config.yml` / `config.yml.example` extraction engine entries
  - Connection sync and schema in `backend/app/services/connection_service.py`
  - Engine resolution in `backend/app/services/document_service.py`
  - Frontend connection form/schema usage in `frontend/components/connections/ConnectionForm.tsx`

## Commit & Pull Request Guidelines
- Recent commits mix imperative summaries and Conventional Commits (e.g., `feat(auth): implement email verification`).
- Keep commit subjects short and action-oriented; use `feat(scope): ...` for new user-facing features.
- PRs should include a clear summary, testing notes, and screenshots for UI changes. Link related issues or docs when applicable.

## Security & Configuration Tips
- Copy `.env.example` to `.env` and never commit secrets.
- See `ADMIN_SETUP.md` for initial admin credentials and setup steps.
