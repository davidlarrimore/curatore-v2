#!/usr/bin/env bash
# Ensure we are running with bash even if invoked via `sh`
[ -n "$BASH_VERSION" ] || exec /usr/bin/env bash "$0" "$@"
# Extraction-service test runner
# - Ensures a Python venv exists using the correct Python version
# - If an existing venv uses the wrong Python version, it is recreated automatically
# - Installs requirements (and dev requirements if present)
# - Optionally runs tests inside Docker (Python 3.12 + Tesseract) when USE_DOCKER=1
# - Runs pytest and writes logs under logs/test_reports/<timestamp>
#
# Env overrides:
#   PYTHON_BIN           Explicit Python interpreter to use (e.g. $(pyenv which python))
#   REQUIRED_PY          Minimum/target Python major.minor (default: read from .python-version or 3.12)
#   RECREATE_VENV        If 1, force recreation of the venv even if version matches (default: 0)
#   REPORT_DIR           Custom report directory (default: logs/test_reports/<timestamp>)
#   USE_DOCKER           If 1, run tests fully inside a docker python:3.12-slim container

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SVC_DIR="$ROOT_DIR/extraction-service"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# Default to timestamped folder suffixed with service name when run directly
REPORT_DIR=${REPORT_DIR:-"$ROOT_DIR/logs/test_reports/${TIMESTAMP}_extraction-service"}
# Default to local venv; Docker only if explicitly requested
USE_DOCKER=${USE_DOCKER:-0}
mkdir -p "$REPORT_DIR"

SUMMARY_FILE="$REPORT_DIR/summary.log"
touch "$SUMMARY_FILE"

log_note() { echo "$*" | tee -a "$SUMMARY_FILE"; }

show_log_tail() {
  local file="$1"; shift
  local title="${1:-Last 200 lines}"
  if [[ -f "$file" ]]; then
    echo "---- $title: $(basename "$file") ----" | tee -a "$SUMMARY_FILE"
    tail -n 200 "$file" | tee -a "$SUMMARY_FILE"
    echo "---- end ----" | tee -a "$SUMMARY_FILE"
  fi
}

print_header() {
  local title="$1"
  echo "========================================" | tee -a "$SUMMARY_FILE"
  echo "$title" | tee -a "$SUMMARY_FILE"
  echo "========================================" | tee -a "$SUMMARY_FILE"
}

# Extract and print a concise pytest summary: passed/failed/skipped
print_pytest_summary() {
  local log_file="$1"
  local also_log_file="${2:-}"
  local passed=0 failed=0 skipped=0 total=0
  if [ -f "$log_file" ]; then
    local line
    line=$(grep -E "[0-9]+ (passed|failed|skipped|error|errors)" "$log_file" | tail -n 1 || true)
    if [ -n "$line" ]; then
      local v
      v=$(echo "$line" | grep -Eo '[0-9]+ passed' | awk '{print $1}' | tail -n1 || true)
      [ -n "${v:-}" ] && passed=$v
      v=$(echo "$line" | grep -Eo '[0-9]+ failed' | awk '{print $1}' | tail -n1 || true)
      [ -n "${v:-}" ] && failed=$v
      v=$(echo "$line" | grep -Eo '[0-9]+ skipped' | awk '{print $1}' | tail -n1 || true)
      [ -n "${v:-}" ] && skipped=$v
    fi
  fi
  total=$((passed + failed + skipped))
  local line_out="Results: total=$total, passed=$passed, failed=$failed, skipped=$skipped"
  log_note "$line_out"
  if [ -n "$also_log_file" ]; then
    echo "$line_out" >>"$also_log_file" 2>/dev/null || true
  fi
}

# Determine required Python version (major.minor)
detect_required_py() {
  local req=""
  if [[ -f "$ROOT_DIR/.python-version" ]]; then
    local full
    full=$(head -n1 "$ROOT_DIR/.python-version" | tr -d "\r" | tr -d " ")
    if [[ "$full" =~ ^([0-9]+)\.([0-9]+) ]]; then
      req="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
    fi
  fi
  echo "${REQUIRED_PY:-${req:-3.12}}"
}

pick_python() {
  # Args: <required_major.minor>
  local minv="$1"
  local candidates=("${PYTHON_BIN:-}" "python${minv}" "python3.${minv#*.}" python3)
  for c in "${candidates[@]}"; do
    [[ -z "$c" ]] && continue
    command -v "$c" >/dev/null 2>&1 || continue
    local v
    v=$("$c" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
    if [[ "$v" == "$minv" || ( "${STRICT_MATCH:-0}" != 1 && $(echo "$v $minv" | awk '{print ($1>=$2)?1:0}') -eq 1 ) ]]; then
      echo "$c"; return 0
    fi
  done
  return 1
}

run_local() {
  local svc="extraction-service"
  local venv="$SVC_DIR/.venv"
  local setup_log="$REPORT_DIR/${svc}_setup.log"
  local test_log="$REPORT_DIR/${svc}.log"

  print_header "Curatore v2: Extraction-Service Tests ($TIMESTAMP)"
  echo "Reports: $REPORT_DIR" | tee -a "$SUMMARY_FILE"

  if [[ ! -d "$SVC_DIR" ]]; then
    log_note "[ERROR] extraction-service directory not found at $SVC_DIR"
    exit 2
  fi

  local req_py
  req_py=$(detect_required_py)
  log_note "Required Python: $req_py.x"

  local py
  if ! py=$(pick_python "$req_py"); then
    log_note "[ERROR] Python $req_py not found. Set PYTHON_BIN or install with pyenv/Homebrew."
    exit 3
  fi
  { echo "Using interpreter: $py"; "$py" -V; } >>"$setup_log" 2>&1
  log_note "Interpreter: $py ($("$py" -V 2>&1))"

  # If a venv exists with the wrong major.minor, or RECREATE_VENV=1, recreate it
  local recreate=${RECREATE_VENV:-0}
  if [[ -d "$venv" && -x "$venv/bin/python" ]]; then
    current_mm=$("$venv/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
    if [[ "$current_mm" != "$req_py" ]]; then
      recreate=1
      echo "Existing venv python ($current_mm) != required ($req_py); will recreate." >>"$setup_log"
    fi
  fi
  if [[ "$recreate" = "1" && -d "$venv" ]]; then
    log_note "Recreating venv for extraction-service …"
    rm -rf "$venv" >>"$setup_log" 2>&1 || true
  fi
  if [[ ! -d "$venv" ]]; then
    log_note "Creating venv at $venv …"
    "$py" -m venv "$venv" >>"$setup_log" 2>&1 || {
      log_note "[ERROR] Failed to create venv — see $(basename "$setup_log")"
      show_log_tail "$setup_log" "extraction-service venv create error"
      exit 4
    }
  fi

  # Install deps
  log_note "Installing extraction-service dependencies …"
  "$venv/bin/python" -m pip install --upgrade pip >>"$setup_log" 2>&1 || true
  if [[ -f "$SVC_DIR/requirements.txt" ]]; then
    if ! "$venv/bin/python" -m pip install -r "$SVC_DIR/requirements.txt" >>"$setup_log" 2>&1; then
      log_note "[WARN] extraction-service: requirements install issues — see $(basename "$setup_log")"
      show_log_tail "$setup_log" "extraction-service requirements install"
    fi
  fi
  if [[ -f "$SVC_DIR/requirements-dev.txt" ]]; then
    "$venv/bin/python" -m pip install -r "$SVC_DIR/requirements-dev.txt" >>"$setup_log" 2>&1 || true
  fi
  # Ensure pytest present
  "$venv/bin/python" -m pip install -U pytest >>"$setup_log" 2>&1 || true
  "$venv/bin/python" -m pytest --version >>"$setup_log" 2>&1 || true

  # Run tests (capture exit code without tripping set -e)
  log_note "Running extraction-service tests (pytest) …"
  local code=0
  (
    cd "$SVC_DIR" && \
    MIN_TEXT_CHARS_FOR_NO_OCR="${MIN_TEXT_CHARS_FOR_NO_OCR:-1}" \
    PYTHONPATH="${SVC_DIR}${PYTHONPATH:+:$PYTHONPATH}" "$venv/bin/python" -m pytest -q
  ) >"$test_log" 2>&1 || code=$?
  print_pytest_summary "$test_log" "$test_log"
  if [[ $code -eq 0 ]]; then
    log_note "[PASS] extraction-service"
    exit 0
  else
    log_note "[FAIL] extraction-service (exit $code) — see $(basename "$test_log")"
    show_log_tail "$test_log" "extraction-service test failure"
    exit $code
  fi
}

run_docker() {
  local svc="extraction-service"
  local test_log="$REPORT_DIR/${svc}.log"
  print_header "Curatore v2: Extraction-Service Tests ($TIMESTAMP)"
  echo "Reports: $REPORT_DIR" | tee -a "$SUMMARY_FILE"
  log_note "Mode: Docker (python:3.12-slim)"
  log_note "Running extraction-service tests (pytest) …"
  if ! docker run --rm \
    -v "$SVC_DIR":/app \
    -w /app \
    python:3.12-slim \
    bash -lc 'set -euo pipefail; \
      apt-get update >/dev/null; \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libreoffice fonts-dejavu-core ca-certificates >/dev/null; \
      python -m pip install --no-cache-dir -U pip >/dev/null; \
      python -m pip install --no-cache-dir -r requirements.txt >/dev/null; \
      if [ -f requirements-dev.txt ]; then python -m pip install --no-cache-dir -r requirements-dev.txt >/dev/null; fi; \
      MIN_TEXT_CHARS_FOR_NO_OCR="${MIN_TEXT_CHARS_FOR_NO_OCR:-1}" python -m pytest -q tests' >"$test_log" 2>&1; then
    print_pytest_summary "$test_log" "$test_log"
    log_note "[FAIL] extraction-service (Docker) — see $(basename "$test_log")"
    show_log_tail "$test_log" "extraction-service (Docker) test failure"
    exit 1
  else
    print_pytest_summary "$test_log" "$test_log"
    log_note "[PASS] extraction-service (Docker)"
    exit 0
  fi
}

main() {
  if [[ "${USE_DOCKER:-0}" = "1" ]]; then
    run_docker "$@"
  else
    run_local "$@"
  fi
}

main "$@"
