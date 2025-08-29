#!/usr/bin/env bash
set -euo pipefail

# Simple end-to-end smoke test for Curatore v2 API (v1 endpoints)
# Requires: curl, jq

BASE_URL=${BASE_URL:-${BASE:-http://localhost:8000}}
OUT_DIR=${OUT_DIR:-scripts/artifacts}
REPORT=${REPORT:-scripts/api_smoke_report_$(date +%Y%m%d_%H%M%S).log}

mkdir -p "$OUT_DIR"
echo "Curatore API smoke test" | tee "$REPORT"
echo "Base URL: $BASE_URL" | tee -a "$REPORT"

fail() { echo "[FAIL] $1" | tee -a "$REPORT"; exit 1; }
pass() { echo "[PASS] $1" | tee -a "$REPORT"; }

req() {
  local method="$1"; shift
  local url="$1"; shift
  echo "\n>>> $method $url" | tee -a "$REPORT"
  # shellcheck disable=SC2086
  curl -sS -D "$OUT_DIR/headers.tmp" -X "$method" "$url" "$@" -o "$OUT_DIR/body.tmp" || return 1
  REQ_CODE=$(awk 'NR==1{print $2}' "$OUT_DIR/headers.tmp")
  echo "HTTP $REQ_CODE" | tee -a "$REPORT"
  # Log request id if present
  REQ_ID=$(awk -F': ' 'BEGIN{IGNORECASE=1} tolower($1)=="x-request-id"{print $2}' "$OUT_DIR/headers.tmp" | tr -d '\r')
  if [[ -n "${REQ_ID:-}" ]]; then echo "X-Request-ID: $REQ_ID" | tee -a "$REPORT"; fi
  sed -n '1,200p' "$OUT_DIR/body.tmp" | tee -a "$REPORT" >/dev/null
  echo "" | tee -a "$REPORT"
}

# 1) Health checks
req GET "$BASE_URL/api/v1/health" || fail "health"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "health returned $code"
pass "health"

req GET "$BASE_URL/api/v1/config/supported-formats" || fail "supported-formats"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "supported-formats $code"
pass "supported-formats"

req GET "$BASE_URL/api/v1/llm/status" || pass "llm-status (LLM may be disabled)"

# 2) Create a temp file and upload
TMP_FILE="$OUT_DIR/sample_$(date +%s).txt"
echo -e "# Curatore Test\n\nThis is a sample file for API smoke test." > "$TMP_FILE"
req POST "$BASE_URL/api/v1/documents/upload" -F "file=@$TMP_FILE" || fail "upload"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "upload $code"
DOC_ID=$(jq -r '.document_id' "$OUT_DIR/body.tmp" 2>/dev/null || echo "")
[[ -n "$DOC_ID" && "$DOC_ID" != "null" ]] || fail "no document_id from upload"
pass "upload ($DOC_ID)"

# 3) Process the uploaded document
PROC_PAYLOAD='{"auto_optimize":true,"quality_thresholds":{"conversion":70,"clarity":7,"completeness":7,"relevance":7,"markdown":7}}'
req POST "$BASE_URL/api/v1/documents/$DOC_ID/process" -H "Content-Type: application/json" --data "$PROC_PAYLOAD" || fail "process"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "process $code"
pass "process"

# 4) Get processing result
req GET "$BASE_URL/api/v1/documents/$DOC_ID/result" || fail "get result"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "get result $code"
pass "get result"

# 5) Fetch processed content
req GET "$BASE_URL/api/v1/documents/$DOC_ID/content" || fail "get content"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "get content $code"
pass "get content"

# 6) Download processed markdown
OUT_MD="$OUT_DIR/${DOC_ID}.md"
echo "\n>>> GET $BASE_URL/api/v1/documents/$DOC_ID/download" | tee -a "$REPORT"
curl -sS -fL "$BASE_URL/api/v1/documents/$DOC_ID/download" -o "$OUT_MD" || fail "download"
[[ -s "$OUT_MD" ]] || fail "download produced empty file"
pass "download ($OUT_MD)"

# 7) List processed documents
req GET "$BASE_URL/api/v1/documents" || fail "list processed"
code="$REQ_CODE"; [[ "$code" == 200 ]] || fail "list processed $code"
pass "list processed"

echo "\nSmoke test complete. Report: $REPORT, Artifacts: $OUT_DIR" | tee -a "$REPORT"
