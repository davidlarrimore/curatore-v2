#!/usr/bin/env bash
set -euo pipefail
echo "🧹 Cleaning up Curatore v2 environment..."
docker-compose down -v --rmi local --remove-orphans || true
echo "✅ Cleanup complete"
