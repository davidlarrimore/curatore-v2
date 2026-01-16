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

## Testing Guidelines
- Backend and extraction service tests use `pytest`; name tests `test_*.py` and keep them near the service they cover.
- Run backend tests with `pytest backend/tests` and extraction tests with `pytest extraction-service/tests -v`.
- Use `./scripts/api_smoke_test.sh` and `./scripts/queue_health.sh` for quick runtime checks.

## Commit & Pull Request Guidelines
- Recent commits mix imperative summaries and Conventional Commits (e.g., `feat(auth): implement email verification`).
- Keep commit subjects short and action-oriented; use `feat(scope): ...` for new user-facing features.
- PRs should include a clear summary, testing notes, and screenshots for UI changes. Link related issues or docs when applicable.

## Security & Configuration Tips
- Copy `.env.example` to `.env` and never commit secrets.
- See `ADMIN_SETUP.md` for initial admin credentials and setup steps.
