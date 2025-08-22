#!/usr/bin/env bash
set -euo pipefail
docker compose down -v --rmi local --remove-orphans || true
echo "All containers, images (local), and volumes removed."
