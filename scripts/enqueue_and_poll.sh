#!/usr/bin/env bash
set -euo pipefail

# Simple helper to enqueue a processing job and poll until completion.
# Usage:
#   scripts/enqueue_and_poll.sh batch <filename> [API_URL]
#   scripts/enqueue_and_poll.sh doc <document_id> [API_URL]

MODE=${1:-}
ARG=${2:-}
API_URL=${3:-${API_URL:-http://localhost:8000}}

if [[ -z "$MODE" || -z "$ARG" ]]; then
  echo "Usage: $0 (batch <filename> | doc <document_id>) [API_URL]" >&2
  exit 1
fi

case "$MODE" in
  batch)
    FILENAME="$ARG"
    STEM=$(basename "$FILENAME")
    STEM="${STEM%.*}"
    DOCUMENT_ID="batch_${STEM}"
    ;;
  doc)
    DOCUMENT_ID="$ARG"
    ;;
  *)
    echo "Unknown mode: $MODE (expected 'batch' or 'doc')" >&2
    exit 1
    ;;
esac

echo "→ Enqueueing document: ${DOCUMENT_ID}"
ENQUEUE_RESP=$(curl -sS -X POST "${API_URL}/api/v1/documents/${DOCUMENT_ID}/process" \
  -H 'Content-Type: application/json' \
  -d '{"auto_optimize": true}')

if echo "$ENQUEUE_RESP" | grep -q 'active_job_id'; then
  echo "⚠️  Conflict: another job is already running for this document" >&2
  if command -v jq >/dev/null 2>&1; then
    echo "$ENQUEUE_RESP" | jq .
  else
    echo "$ENQUEUE_RESP"
  fi
  exit 2
fi

JOB_ID=$(echo "$ENQUEUE_RESP" | sed -n 's/.*"job_id"\s*:\s*"\([^"]*\)".*/\1/p')
if [[ -z "$JOB_ID" ]]; then
  echo "Failed to parse job_id from response:" >&2
  echo "$ENQUEUE_RESP" >&2
  exit 3
fi
echo "→ Job ID: $JOB_ID"

POLL_INTERVAL=${POLL_INTERVAL:-2}
MAX_WAIT=${MAX_WAIT:-600} # seconds

echo "→ Polling every ${POLL_INTERVAL}s (timeout ${MAX_WAIT}s)"
START=$(date +%s)

while true; do
  RESP=$(curl -sS "${API_URL}/api/v1/jobs/${JOB_ID}") || true
  STATUS=$(echo "$RESP" | sed -n 's/.*"status"\s*:\s*"\([^"]*\)".*/\1/p' | tr '[:lower:]' '[:upper:]')
  NOW=$(date +%s)
  ELAPSED=$((NOW-START))

  if [[ "$STATUS" == "SUCCESS" ]]; then
    echo "✅ Job completed in ${ELAPSED}s"
    if command -v jq >/dev/null 2>&1; then
      echo "$RESP" | jq .
    else
      echo "$RESP"
    fi
    exit 0
  elif [[ "$STATUS" == "FAILURE" ]]; then
    echo "❌ Job failed after ${ELAPSED}s"
    if command -v jq >/dev/null 2>&1; then
      echo "$RESP" | jq .
    else
      echo "$RESP"
    fi
    exit 4
  fi

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    echo "⏰ Timeout after ${MAX_WAIT}s" >&2
    if command -v jq >/dev/null 2>&1; then
      echo "$RESP" | jq .
    else
      echo "$RESP"
    fi
    exit 5
  fi

  sleep "$POLL_INTERVAL"
done

