# Next.js + Tailwind + FastAPI (Docker) — Starter

A minimal, modern multi-tier web app:
- **Frontend:** Next.js 14 (App Router) + TailwindCSS
- **Backend:** Python + FastAPI
- **Dev Runtime:** Docker + docker-compose with hot-reload for both tiers

## Prereqs (macOS)
1. Install **Docker Desktop for Mac** and keep it running.
2. Open the **Terminal** app.

> You do **not** need Node.js or Python on your host — everything runs in containers.

## One-time setup
```bash
cd react-fastapi-next-docker-starter
chmod +x scripts/*.sh
./scripts/init.sh
```

## Run the stack (dev)
```bash
./scripts/dev-up.sh
```
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs

## Stop everything
```bash
./scripts/dev-down.sh
```

## Clean up images & volumes (optional "nuke")
```bash
./scripts/nuke.sh
```

## Project structure
```
react-fastapi-next-docker-starter/
  ├─ backend/
  │  ├─ app/
  │  │  ├─ __init__.py
  │  │  └─ main.py
  │  ├─ requirements.txt
  │  └─ Dockerfile
  ├─ frontend/
  │  ├─ app/
  │  │  └─ page.jsx
  │  ├─ public/
  │  ├─ styles/
  │  │  └─ globals.css
  │  ├─ components/
  │  │  └─ ItemsList.jsx
  │  ├─ next.config.mjs
  │  ├─ package.json
  │  ├─ postcss.config.js
  │  ├─ tailwind.config.js
  │  └─ Dockerfile
  ├─ scripts/
  │  ├─ init.sh
  │  ├─ dev-up.sh
  │  ├─ dev-down.sh
  │  └─ nuke.sh
  └─ docker-compose.yml
```

## Notes
- Frontend uses `NEXT_PUBLIC_API_URL` to call the API (defaults to `http://localhost:8000` via docker-compose).
- CORS on the backend is configured for `http://localhost:3000` (Next.js dev server).
- Edit files locally — both services hot-reload automatically.
