#!/usr/bin/env bash
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000}

echo "→ Checking queue health at ${API_URL}/api/v1/system/queues"
resp=$(curl -sS "${API_URL}/api/v1/system/queues")

if command -v jq >/dev/null 2>&1; then
  echo "$resp" | jq .
else
  echo "$resp"
fi

