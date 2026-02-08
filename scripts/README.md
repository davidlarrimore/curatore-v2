# Curatore v2 Scripts

This directory contains utility scripts for Curatore v2 operations.

## Directory Structure

```
scripts/
├── sam/                      # SAM.gov integration scripts
│   ├── sam_pull.py          # Daily pull from SAM.gov API
│   ├── README.md            # SAM.gov documentation
│   └── HOW_TO_RUN.md        # Detailed execution guide
├── sharepoint/              # SharePoint integration scripts
│   ├── sharepoint_connect.py
│   ├── sharepoint_inventory.py
│   ├── sharepoint_download.py
│   └── sharepoint_process.py
├── dev-up.sh               # Start all services
├── dev-down.sh             # Stop all services
├── dev-logs.sh             # View service logs
└── README.md               # This file
```

## SAM.gov Integration

Scripts for pulling government contracting opportunities from SAM.gov API.

**Quick Start:**
```bash
# 1. Setup (one-time)
./scripts/dev-up.sh
./scripts/init_storage.sh
cd backend && python -m app.core.commands.seed --create-admin

# 2. Configure .env
SAM_API_KEY=your-sam-gov-api-key
DEFAULT_ORG_ID=your-org-uuid-from-seed

# 3. Run the script (EASIEST - auto-configures Python environment)
./scripts/sam/run.sh

# Alternative methods:
# Via Docker
docker-compose exec backend python /app/scripts/sam/sam_pull.py

# Via backend venv
cd backend && source venv/bin/activate && cd ..
python scripts/sam/sam_pull.py
```

**What it does:**
- Fetches opportunities from last 24 hours
- Filters for DHS agencies (ICE, CBP, USCIS)
- Filters for RFI/Solicitation notice types
- Uploads to MinIO: `{bucket}/{org_id}/rfi/{filename}.json`
- Creates database artifact for frontend visibility

**View results:**
- Frontend: http://localhost:3000/storage → Default Storage → {org_id} → rfi/
- MinIO Console: http://localhost:9001 (admin/changeme)

**Documentation:**
- `sam/README.md` - Full documentation
- `sam/HOW_TO_RUN.md` - Step-by-step execution guide

## Development Scripts

### dev-up.sh
Start all Curatore services (backend, frontend, worker, redis, extraction)

### dev-down.sh
Stop all Curatore services

### dev-logs.sh
View logs for all or specific services

### dev-restart.sh
Restart specific services with optional rebuild

### init_storage.sh
Initialize MinIO storage buckets and lifecycle policies

### clean.sh
Clean up Docker containers, volumes, and images

### nuke.sh
Nuclear option - remove everything including networks

## SharePoint Integration

Scripts for SharePoint/Microsoft Graph integration:

- `sharepoint/sharepoint_connect.py` - Test connectivity
- `sharepoint/sharepoint_inventory.py` - List folder contents
- `sharepoint/sharepoint_download.py` - Download files
- `sharepoint/sharepoint_process.py` - End-to-end workflow

## Testing Scripts

### api_smoke_test.sh
Quick API health checks

### run_all_tests.sh
Run all tests across services

### queue_health.sh
Check Redis and Celery queue health

### enqueue_and_poll.sh
Enqueue document and poll for completion

## Configuration Migration

### migrate_env_to_yaml.py
Migrate .env configuration to config.yml format

```bash
python scripts/migrate_env_to_yaml.py
```
