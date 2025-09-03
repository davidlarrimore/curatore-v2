#!/usr/bin/env bash
# Ensure we are running with bash even if invoked via `sh`
[ -n "$BASH_VERSION" ] || exec /usr/bin/env bash "$0" "$@"
# Run tests for all services sequentially and log results.
# - Creates a timestamped report directory under logs/test_reports
# - Pre-flight: verify app is not already running (ports 8000/3000)
# - Sets up per-service test environments (Python venvs, Node deps) as needed
# - Runs backend pytest, extraction-service pytest (if present), and frontend npm test (if defined)
# - Summarizes PASS/WARN/FAIL per service and exits nonzero on failures

set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_DIR=${REPORT_DIR:-"$ROOT_DIR/logs/test_reports/$TIMESTAMP"}
mkdir -p "$REPORT_DIR"

SUMMARY_FILE="$REPORT_DIR/summary.log"
touch "$SUMMARY_FILE"

# By default, recreate Python virtualenvs on each run unless explicitly disabled
export RECREATE_VENV=${RECREATE_VENV:-1}

log_note() {
  echo "$*" | tee -a "$SUMMARY_FILE"
}

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

record_result() {
  local service="$1"; shift
  local status="$1"; shift
  local note="${1:-}"
  RESULTS+=("$service:$status:${note}")
}

# -------- Pre-flight: ensure app not already running --------
port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn | awk '{print $4}' | grep -E "[:\.]$port$" -q
    return $?
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn | awk '{print $4}' | grep -E "[:\.]$port$" -q
    return $?
  else
    return 1
  fi
}

preflight_check_ports() {
  local -a ports=(8000 3000)
  local used=()
  for p in "${ports[@]}"; do
    if port_in_use "$p"; then
      used+=("$p")
    fi
  done
  if (( ${#used[@]} > 0 )) && [[ "${ALLOW_RUNNING_APP:-0}" != "1" ]]; then
    log_note "[ERROR] Detected application ports in use: ${used[*]}"
    log_note "        Please stop running instances (dev server/docker) or set ALLOW_RUNNING_APP=1 to proceed."
    exit 2
  fi
}

preflight_check_ports

# -------- Helpers: environment setup --------
ensure_python_venv() {
  # Args: <service_name> <service_dir> <requirements_path> [min_python_major.minor]
  local name="$1"; shift
  local dir="$1"; shift
  local req="$1"; shift || true
  local min_py="${1:-}"
  local venv="$dir/.venv"
  local log="$REPORT_DIR/${name}_setup.log"

  if [[ ! -d "$dir" ]]; then
    log_note "[WARN] $name: directory not found (env not created)"
    return 1
  fi

  # Pick a Python interpreter that meets the minimum version
  pick_python() {
    local minv="$1"
    # Prefer Python 3.12 explicitly; do not fall back to lower minors when a minimum is provided
    local candidates=("${PYTHON_BIN:-}" python3.12 python3)
    for c in "${candidates[@]}"; do
      [[ -z "$c" ]] && continue
      command -v "$c" >/dev/null 2>&1 || continue
      if [[ -n "$minv" ]]; then
        local v; v=$("$c" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
        local maj min reqmaj reqmin
        IFS='.' read -r maj min <<< "$v"
        IFS='.' read -r reqmaj reqmin <<< "$minv"
        if (( maj > reqmaj || (maj == reqmaj && min >= reqmin) )); then
          echo "$c"; return 0
        fi
      else
        echo "$c"; return 0
      fi
    done
    return 1
  }

  local py
  py=$(pick_python "$min_py") || true
  if [[ -z "$py" ]]; then
    log_note "[WARN] $name: Python $min_py+ not found. Install Python $min_py (pyenv/Homebrew) or set PYTHON_BIN."
    return 1
  fi

  # Log chosen interpreter
  { echo "Using interpreter: $py"; "$py" -V; } >>"$log" 2>&1
  log_note "[$name] Python interpreter: $py ($("$py" -V 2>&1))"
  local created=0
  # If a venv exists but its interpreter does not meet min_py, force recreation
  if [[ -d "$venv" && -n "$min_py" && -x "$venv/bin/python" ]]; then
    current_ver=$("$venv/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
    if [[ "$current_ver" != $(echo "$min_py" | cut -d. -f1-2) ]]; then
      export RECREATE_VENV=1
    fi
  fi

  if [[ "${RECREATE_VENV:-0}" = "1" && -d "$venv" ]]; then
    log_note "Recreating venv for $name …"
    rm -rf "$venv" 2>>"$log" || true
    # Fallback removal if rm -rf had issues with locked files
    if [[ -d "$venv" ]]; then
      if command -v python >/dev/null 2>&1; then
        python - <<'PY' "$venv" >>"$log" 2>&1 || true
import os, shutil, sys
path = sys.argv[1]
try:
    shutil.rmtree(path)
except Exception as e:
    print(f"shutil.rmtree failed: {e}")
PY
      fi
    fi
    # As a last resort, rename so a fresh venv can be created
    if [[ -d "$venv" ]]; then
      mv "$venv" "${venv}.old_${TIMESTAMP}" 2>>"$log" || true
    fi
  fi
  if [[ ! -d "$venv" ]]; then
    log_note "Creating venv for $name at $venv …"
    "$py" -m venv "$venv" >"$log" 2>&1 || {
      log_note "[WARN] $name: failed to create venv — see $(basename "$log")"
      show_log_tail "$log" "$name venv create error"
      return 1
    }
    created=1
  fi
  # Only install requirements on first creation unless FORCE_INSTALL_DEPS=1
  if [[ $created -eq 1 || "${FORCE_INSTALL_DEPS:-0}" = "1" ]]; then
    if [[ -n "${req:-}" && -f "$req" ]]; then
      log_note "Installing $name dependencies from $(basename "$req") …"
      "$venv/bin/python" -m pip install --upgrade pip >"$log" 2>&1 || true
      if ! "$venv/bin/python" -m pip install -r "$req" >>"$log" 2>&1; then
        log_note "[WARN] $name: dependency install failed — see $(basename "$log")"
        show_log_tail "$log" "$name dependency install"
      fi
    fi
    # Ensure pytest is available for test execution
    echo "Ensuring pytest is installed for $name …" >>"$log" 2>&1
    "$venv/bin/python" -m pip install -U pytest >>"$log" 2>&1 || true
    "$venv/bin/python" -m pip list >>"$log" 2>&1 || true
  fi
  LAST_VENV_CREATED=$created
  echo "$venv"
}

run_backend_tests() {
  local svc="backend"
  local subdir="$REPORT_DIR/$svc"
  mkdir -p "$subdir"
  if [[ ! -d "$ROOT_DIR/backend" ]]; then
    log_note "[WARN] $svc: directory not found"
    record_result "$svc" "WARN" "directory not found"
    return 0
  fi
  log_note "Running $svc via backend/scripts/run_tests.sh …"
  (
    REPORT_DIR="$subdir" RECREATE_VENV="${RECREATE_VENV:-1}" PYTHON_BIN="${PYTHON_BIN:-}" \
    bash "$ROOT_DIR/backend/scripts/run_tests.sh"
  ) | tee -a "$SUMMARY_FILE"
  local code=${PIPESTATUS[0]}
  # Surface concise results from the service log into the parent summary
  if [[ -f "$subdir/${svc}.log" ]]; then
    res_line=$(grep -E "^Results: total=.*" "$subdir/${svc}.log" | tail -n 1 || true)
    [[ -n "$res_line" ]] && echo "$res_line" | tee -a "$SUMMARY_FILE"
  fi
  if [[ $code -eq 0 ]]; then
    record_result "$svc" "PASS"
  else
    record_result "$svc" "FAIL" "exit $code"
  fi
}

run_extraction_service_tests() {
  local svc="extraction-service"
  local subdir="$REPORT_DIR/$svc"
  mkdir -p "$subdir"
  if [[ ! -d "$ROOT_DIR/extraction-service" ]]; then
    log_note "[WARN] $svc: directory not found"
    record_result "$svc" "WARN" "directory not found"
    return 0
  fi
  log_note "Running $svc via extraction-service/scripts/run_tests.sh …"
  (
    REPORT_DIR="$subdir" RECREATE_VENV="${RECREATE_VENV:-1}" USE_DOCKER="${USE_DOCKER_EXTRACTION:-0}" \
    bash "$ROOT_DIR/extraction-service/scripts/run_tests.sh"
  ) | tee -a "$SUMMARY_FILE"
  local code=${PIPESTATUS[0]}
  # Surface concise results from the service log into the parent summary
  if [[ -f "$subdir/${svc}.log" ]]; then
    res_line=$(grep -E "^Results: total=.*" "$subdir/${svc}.log" | tail -n 1 || true)
    [[ -n "$res_line" ]] && echo "$res_line" | tee -a "$SUMMARY_FILE"
  fi
  if [[ $code -eq 0 ]]; then
    record_result "$svc" "PASS"
  else
    record_result "$svc" "FAIL" "exit $code"
  fi
}

run_frontend_tests() {
  local svc="frontend"
  local svc_dir="$ROOT_DIR/frontend"
  local subdir="$REPORT_DIR/$svc"
  mkdir -p "$subdir"
  local log="$subdir/${svc}.log"

  if [[ ! -d "$svc_dir" ]]; then
    echo "[WARN] $svc: directory not found" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "directory not found"
    return 0
  fi

  if [[ ! -f "$svc_dir/package.json" ]]; then
    echo "[WARN] $svc: package.json not found" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "no package.json"
    return 0
  fi

  # Detect package manager
  local runner cmd
  if [[ -f "$svc_dir/pnpm-lock.yaml" ]] && command -v pnpm >/dev/null 2>&1; then
    runner="pnpm"
    cmd=(pnpm -C "$svc_dir" -s test)
  elif [[ -f "$svc_dir/yarn.lock" ]] && command -v yarn >/dev/null 2>&1; then
    runner="yarn"
    cmd=(yarn --cwd "$svc_dir" test -s)
  else
    runner="npm"
    if ! command -v npm >/dev/null 2>&1; then
      echo "[WARN] $svc: npm not installed" | tee -a "$SUMMARY_FILE"
      record_result "$svc" "WARN" "npm missing"
      return 0
    fi
    cmd=(npm --prefix "$svc_dir" run -s test --if-present)
  fi

  # Check if a test script exists without requiring jq
  if ! grep -q '"test"\s*:' "$svc_dir/package.json"; then
    echo "[WARN] $svc: no test script defined" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "no test script"
    return 0
  fi

  # Ensure node modules installed (best-effort)
  if [[ ! -d "$svc_dir/node_modules" ]]; then
    echo "Installing $svc dependencies (node) …"
    if [[ "$runner" = "pnpm" ]]; then
      pnpm -C "$svc_dir" -s install >"$REPORT_DIR/${svc}_setup.log" 2>&1 || echo "[WARN] $svc: pnpm install failed" | tee -a "$SUMMARY_FILE"
    elif [[ "$runner" = "yarn" ]]; then
      yarn --cwd "$svc_dir" install --silent >"$REPORT_DIR/${svc}_setup.log" 2>&1 || echo "[WARN] $svc: yarn install failed" | tee -a "$SUMMARY_FILE"
    else
      npm --prefix "$svc_dir" ci --silent >"$REPORT_DIR/${svc}_setup.log" 2>&1 || npm --prefix "$svc_dir" install --silent >"$REPORT_DIR/${svc}_setup.log" 2>&1 || echo "[WARN] $svc: npm install failed" | tee -a "$SUMMARY_FILE"
    fi
  fi

  echo "Running $svc tests ($runner test) …" | tee -a "$SUMMARY_FILE"
  "${cmd[@]}" >"$log" 2>&1
  local code=$?
  if [[ $code -eq 0 ]]; then
    echo "[PASS] $svc" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "PASS"
  else
    echo "[FAIL] $svc (exit $code) — see $(basename "$log")" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "FAIL" "exit $code"
  fi
}

RESULTS=()
print_header "Curatore v2: Test Run ($TIMESTAMP)"
echo "Reports: $REPORT_DIR" | tee -a "$SUMMARY_FILE"
echo "Recreate venvs (RECREATE_VENV): ${RECREATE_VENV}" | tee -a "$SUMMARY_FILE"

# Execute suites sequentially
run_backend_tests
run_extraction_service_tests
run_frontend_tests

echo "" | tee -a "$SUMMARY_FILE"
print_header "Summary"

fail_count=0
warn_count=0
pass_count=0

for entry in "${RESULTS[@]}"; do
  IFS=":" read -r svc status note <<< "$entry"
  case "$status" in
    PASS) ((pass_count++)); echo "[PASS] $svc" | tee -a "$SUMMARY_FILE" ;;
    WARN) ((warn_count++)); echo "[WARN] $svc${note:+ — $note}" | tee -a "$SUMMARY_FILE" ;;
    FAIL) ((fail_count++)); echo "[FAIL] $svc${note:+ — $note}" | tee -a "$SUMMARY_FILE" ;;
  esac
done

echo "" | tee -a "$SUMMARY_FILE"
echo "Totals: PASS=$pass_count, WARN=$warn_count, FAIL=$fail_count" | tee -a "$SUMMARY_FILE"

if [[ $fail_count -gt 0 ]]; then
  exit 1
fi

exit 0
