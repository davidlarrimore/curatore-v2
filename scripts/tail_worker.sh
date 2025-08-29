#!/usr/bin/env bash
set -euo pipefail

if command -v docker-compose >/dev/null 2>&1; then
  echo "→ Tailing Celery worker logs (docker-compose)"
  exec docker-compose logs -f worker
else
  echo "docker-compose not found. Trying docker logs for container 'curatore-worker'"
  exec docker logs -f curatore-worker
fi

