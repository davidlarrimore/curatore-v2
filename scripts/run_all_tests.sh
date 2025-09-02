#!/usr/bin/env bash
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
    echo "[ERROR] Detected application ports in use: ${used[*]}" | tee -a "$SUMMARY_FILE"
    echo "        Please stop running instances (dev server/docker) or set ALLOW_RUNNING_APP=1 to proceed." | tee -a "$SUMMARY_FILE"
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
    echo "[WARN] $name: directory not found (env not created)" | tee -a "$SUMMARY_FILE"
    return 1
  fi

  # Pick a Python interpreter that meets the minimum version
  pick_python() {
    local minv="$1"
    local candidates=("${PYTHON_BIN:-}" python3.12 python3.11 python3.10 python3 python)
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
    echo "[WARN] $name: Python $min_py+ not found. Install a newer Python (pyenv/Homebrew) or set PYTHON_BIN." | tee -a "$SUMMARY_FILE"
    return 1
  fi

  # Log chosen interpreter
  { echo "Using interpreter: $py"; "$py" -V; } >>"$log" 2>&1
  local created=0
  if [[ "${RECREATE_VENV:-0}" = "1" && -d "$venv" ]]; then
    echo "Recreating venv for $name …" | tee -a "$SUMMARY_FILE"
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
    echo "Creating venv for $name at $venv …"
    "$py" -m venv "$venv" >"$log" 2>&1 || {
      echo "[WARN] $name: failed to create venv — see $(basename "$log")" | tee -a "$SUMMARY_FILE"
      return 1
    }
    created=1
  fi
  # Only install requirements on first creation unless FORCE_INSTALL_DEPS=1
  if [[ $created -eq 1 || "${FORCE_INSTALL_DEPS:-0}" = "1" ]]; then
    if [[ -n "${req:-}" && -f "$req" ]]; then
      echo "Installing $name dependencies from $(basename "$req") …"
      "$venv/bin/python" -m pip install --upgrade pip >"$log" 2>&1 || true
      if ! "$venv/bin/python" -m pip install -r "$req" >>"$log" 2>&1; then
        echo "[WARN] $name: dependency install failed — see $(basename "$log")" | tee -a "$SUMMARY_FILE"
      fi
    fi
    # Ensure pytest is available for test execution
    echo "Ensuring pytest is installed for $name …" >>"$log" 2>&1
    "$venv/bin/python" -m pip install -U pytest >>"$log" 2>&1 || true
  fi
  LAST_VENV_CREATED=$created
  echo "$venv"
}

run_backend_tests() {
  local svc="backend"
  local svc_dir="$ROOT_DIR/backend"
  local log="$REPORT_DIR/${svc}.log"

  if [[ ! -d "$svc_dir" ]]; then
    echo "[WARN] $svc: directory not found" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "directory not found"
    return 0
  fi

  # Ensure venv and deps
  local venv
  local min_py_req="3.11"
  venv=$(ensure_python_venv "$svc" "$svc_dir" "$svc_dir/requirements.txt" "$min_py_req") || true
  if [[ -z "${venv:-}" ]]; then
    record_result "$svc" "WARN" "python>=$min_py_req not found"
    return 0
  fi
  local py_cmd="pytest"
  if [[ -n "${venv:-}" && -x "$venv/bin/python" ]]; then
    py_cmd="$venv/bin/python -m pytest"
    # Try to ensure dev deps if available, especially pytest
    if [[ -f "$svc_dir/requirements-dev.txt" ]]; then
      echo "Ensuring $svc dev dependencies …" >>"$REPORT_DIR/${svc}_setup.log" 2>&1
      if ! "$venv/bin/python" -m pip install -r "$svc_dir/requirements-dev.txt" >>"$REPORT_DIR/${svc}_setup.log" 2>&1; then
        echo "[WARN] $svc: dev dependency install failed — see ${svc}_setup.log" | tee -a "$SUMMARY_FILE"
      fi
    fi
    # Ensure pytest present in the venv even if not in requirements
    echo "Verifying pytest availability …" >>"$REPORT_DIR/${svc}_setup.log" 2>&1
    "$venv/bin/python" -m pytest --version >>"$REPORT_DIR/${svc}_setup.log" 2>&1 || {
      echo "Installing pytest into $svc venv …" >>"$REPORT_DIR/${svc}_setup.log" 2>&1
      "$venv/bin/python" -m pip install -U pytest >>"$REPORT_DIR/${svc}_setup.log" 2>&1 || true
    }
    "$venv/bin/python" -m pytest --version >>"$REPORT_DIR/${svc}_setup.log" 2>&1 || true
    if ! "$venv/bin/python" -m pytest --version >/dev/null 2>&1; then
      echo "[WARN] $svc: pytest not available in venv after install attempt" | tee -a "$SUMMARY_FILE"
      record_result "$svc" "WARN" "pytest missing"
      return 0
    fi
  elif ! command -v pytest >/dev/null 2>&1; then
    echo "[WARN] $svc: pytest not available" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "pytest missing"
    return 0
  fi

  echo "Running $svc tests (pytest) …"
  (
    cd "$ROOT_DIR" && \
    PYTHONPATH="backend${PYTHONPATH:+:$PYTHONPATH}" bash -lc "$py_cmd -q"
  ) >"$log" 2>&1
  local code=$?
  if [[ $code -eq 0 ]]; then
    echo "[PASS] $svc" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "PASS"
  else
    echo "[FAIL] $svc (exit $code) — see $(basename "$log")" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "FAIL" "exit $code"
  fi
}

run_extraction_service_tests() {
  local svc="extraction-service"
  local svc_dir="$ROOT_DIR/extraction-service"
  local test_dir="$svc_dir/tests"
  local log="$REPORT_DIR/${svc}.log"

  if [[ ! -d "$svc_dir" ]]; then
    echo "[WARN] $svc: directory not found" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "directory not found"
    return 0
  fi

  if [[ ! -d "$test_dir" ]]; then
    echo "[WARN] $svc: no tests found" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "no tests"
    return 0
  fi

  # Ensure venv and deps
  local venv
  local min_py_req="3.10"
  venv=$(ensure_python_venv "$svc" "$svc_dir" "$svc_dir/requirements.txt" "$min_py_req") || true
  if [[ -z "${venv:-}" ]]; then
    record_result "$svc" "WARN" "python>=$min_py_req not found"
    return 0
  fi
  local py_cmd="pytest"
  if [[ -n "${venv:-}" && -x "$venv/bin/python" ]]; then
    py_cmd="$venv/bin/python -m pytest"
    # Try to ensure dev deps if available, especially pytest
    if [[ -f "$svc_dir/requirements-dev.txt" ]]; then
      echo "Ensuring $svc dev dependencies …" >>"$REPORT_DIR/${svc}_setup.log" 2>&1
      if ! "$venv/bin/python" -m pip install -r "$svc_dir/requirements-dev.txt" >>"$REPORT_DIR/${svc}_setup.log" 2>&1; then
        echo "[WARN] $svc: dev dependency install failed — see ${svc}_setup.log" | tee -a "$SUMMARY_FILE"
      fi
    fi
    # Ensure pytest present in the venv even if not in requirements
    echo "Verifying pytest availability …" >>"$REPORT_DIR/${svc}_setup.log" 2>&1
    "$venv/bin/python" -m pytest --version >>"$REPORT_DIR/${svc}_setup.log" 2>&1 || {
      echo "Installing pytest into $svc venv …" >>"$REPORT_DIR/${svc}_setup.log" 2>&1
      "$venv/bin/python" -m pip install -U pytest >>"$REPORT_DIR/${svc}_setup.log" 2>&1 || true
    }
    "$venv/bin/python" -m pytest --version >>"$REPORT_DIR/${svc}_setup.log" 2>&1 || true
    if ! "$venv/bin/python" -m pytest --version >/dev/null 2>&1; then
      echo "[WARN] $svc: pytest not available in venv after install attempt" | tee -a "$SUMMARY_FILE"
      record_result "$svc" "WARN" "pytest missing"
      return 0
    fi
  elif ! command -v pytest >/dev/null 2>&1; then
    echo "[WARN] $svc: pytest not available" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "WARN" "pytest missing"
    return 0
  fi

  echo "Running $svc tests (pytest) …"
  (
    cd "$svc_dir" && \
    PYTHONPATH="${svc_dir}${PYTHONPATH:+:$PYTHONPATH}" bash -lc "$py_cmd -q"
  ) >"$log" 2>&1
  local code=$?
  if [[ $code -eq 0 ]]; then
    echo "[PASS] $svc" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "PASS"
  else
    echo "[FAIL] $svc (exit $code) — see $(basename "$log")" | tee -a "$SUMMARY_FILE"
    record_result "$svc" "FAIL" "exit $code"
  fi
}

run_frontend_tests() {
  local svc="frontend"
  local svc_dir="$ROOT_DIR/frontend"
  local log="$REPORT_DIR/${svc}.log"

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

  echo "Running $svc tests ($runner test) …"
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
