#!/usr/bin/env bash
set -euo pipefail

echo "[init] Building images..."
docker compose build

echo "[init] Done."
