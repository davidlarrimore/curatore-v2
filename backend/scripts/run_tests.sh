#!/usr/bin/env bash
# Ensure we are running with bash even if invoked via `sh`
[ -n "$BASH_VERSION" ] || exec /usr/bin/env bash "$0" "$@"
# Backend test runner
# - Ensures a Python venv exists for the backend using the correct Python version
# - If an existing venv uses the wrong Python version, it is recreated automatically
# - Installs requirements (and dev requirements if present)
# - Runs pytest and writes logs under logs/test_reports/<timestamp>
#
# Env overrides:
#   PYTHON_BIN           Explicit Python interpreter to use (e.g. $(pyenv which python))
#   REQUIRED_PY          Minimum/target Python major.minor (default: read from .python-version or 3.12)
#   RECREATE_VENV        If 1, force recreation of the venv even if version matches (default: 0)
#   REPORT_DIR           Custom report directory (default: logs/test_reports/<timestamp>)

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BACKEND_DIR="$ROOT_DIR/backend"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# Default to timestamped folder suffixed with service name when run directly
REPORT_DIR=${REPORT_DIR:-"$ROOT_DIR/logs/test_reports/${TIMESTAMP}_backend"}
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
  local passed=0 failed=0 skipped=0 total=0
  if [ -f "$log_file" ]; then
    local line
    line=$(grep -E "[0-9]+ (passed|failed|skipped)" "$log_file" | tail -n 1 || true)
    if [ -n "$line" ]; then
      local v
      v=$(echo "$line" | grep -Eo '[0-9]+ passed' | awk '{print $1}' | tail -n1)
      [ -n "$v" ] && passed=$v
      v=$(echo "$line" | grep -Eo '[0-9]+ failed' | awk '{print $1}' | tail -n1)
      [ -n "$v" ] && failed=$v
      v=$(echo "$line" | grep -Eo '[0-9]+ skipped' | awk '{print $1}' | tail -n1)
      [ -n "$v" ] && skipped=$v
    fi
  fi
  total=$((passed + failed + skipped))
  log_note "Results: total=$total, passed=$passed, failed=$failed, skipped=$skipped"
}

# Determine required Python version (major.minor)
detect_required_py() {
  local req=""
  if [[ -f "$ROOT_DIR/.python-version" ]]; then
    # Read first token like 3.12.4 and reduce to 3.12
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

run() {
  local svc="backend"
  local venv="$BACKEND_DIR/.venv"
  local setup_log="$REPORT_DIR/${svc}_setup.log"
  local test_log="$REPORT_DIR/${svc}.log"

  print_header "Curatore v2: Backend Tests ($TIMESTAMP)"
  echo "Reports: $REPORT_DIR" | tee -a "$SUMMARY_FILE"

  if [[ ! -d "$BACKEND_DIR" ]]; then
    log_note "[ERROR] backend directory not found at $BACKEND_DIR"
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
  {
    echo "Using interpreter: $py"
    "$py" -V
  } >>"$setup_log" 2>&1
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
    log_note "Recreating venv for backend …"
    rm -rf "$venv" >>"$setup_log" 2>&1 || true
  fi

  if [[ ! -d "$venv" ]]; then
    log_note "Creating venv at $venv …"
    "$py" -m venv "$venv" >>"$setup_log" 2>&1 || {
      log_note "[ERROR] Failed to create venv — see $(basename "$setup_log")"
      show_log_tail "$setup_log" "backend venv create error"
      exit 4
    }
  fi

  # Install deps
  log_note "Installing backend dependencies …"
  "$venv/bin/python" -m pip install --upgrade pip >>"$setup_log" 2>&1 || true
  if [[ -f "$BACKEND_DIR/requirements.txt" ]]; then
    if ! "$venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt" >>"$setup_log" 2>&1; then
      log_note "[WARN] backend: requirements install issues — see $(basename "$setup_log")"
      show_log_tail "$setup_log" "backend requirements install"
    fi
  fi
  if [[ -f "$BACKEND_DIR/requirements-dev.txt" ]]; then
    "$venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements-dev.txt" >>"$setup_log" 2>&1 || true
  fi
  # Ensure pytest present
  "$venv/bin/python" -m pip install -U pytest >>"$setup_log" 2>&1 || true
  "$venv/bin/python" -m pytest --version >>"$setup_log" 2>&1 || true

  # Run tests (do not let set -e abort before we summarize)
  log_note "Running backend tests (pytest) …"
  local code=0
  (
    cd "$ROOT_DIR" && \
    PYTHONPATH="backend${PYTHONPATH:+:$PYTHONPATH}" "$venv/bin/python" -m pytest -q
  ) >"$test_log" 2>&1 || code=$?
  print_pytest_summary "$test_log"
  if [[ $code -eq 0 ]]; then
    log_note "[PASS] backend"
    exit 0
  else
    log_note "[FAIL] backend (exit $code) — see $(basename "$test_log")"
    show_log_tail "$test_log" "backend test failure"
    exit $code
  fi
}

run "$@"
