#!/usr/bin/env bash
# Ensure we are running with bash even if invoked via `sh`
[ -n "$BASH_VERSION" ] || exec /usr/bin/env bash "$0" "$@"
# Run tests for all services sequentially and log results.
# - Creates a timestamped report directory under logs/test_reports
# - Pre-flight: verify app is not already running (ports 8000/3000)
# - Runs linting (Ruff for Python, ESLint for frontend)
# - Runs dependency vulnerability scanning (pip-audit, npm audit)
# - Sets up per-service test environments (Python venvs, Node deps) as needed
# - Runs backend pytest, mcp pytest, and frontend npm test
# - Summarizes PASS/WARN/FAIL per service and exits nonzero on failures
#
# Env overrides:
#   SKIP_LINT=1        Skip linting steps
#   SKIP_COVERAGE=1    Omit --cov flags from pytest commands
#   SKIP_DEP_SCAN=1    Skip dependency vulnerability scanning

set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_DIR=${REPORT_DIR:-"$ROOT_DIR/logs/test_reports/$TIMESTAMP"}
mkdir -p "$REPORT_DIR"

SUMMARY_FILE="$REPORT_DIR/summary.log"
touch "$SUMMARY_FILE"

# By default, recreate Python virtualenvs on each run unless explicitly disabled
export RECREATE_VENV=${RECREATE_VENV:-1}

# Optional skip flags
SKIP_LINT=${SKIP_LINT:-0}
SKIP_COVERAGE=${SKIP_COVERAGE:-0}
SKIP_DEP_SCAN=${SKIP_DEP_SCAN:-0}

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

# -------- Linting --------
run_python_lint() {
  if [[ "$SKIP_LINT" = "1" ]]; then
    log_note "[SKIP] Python lint (SKIP_LINT=1)"
    return 0
  fi

  print_header "Python Lint (Ruff)"
  local log="$REPORT_DIR/python_lint.log"
  local venv="$ROOT_DIR/backend/.venv"

  # Ensure backend venv exists (needed to install ruff)
  if [[ ! -d "$venv" ]]; then
    log_note "[WARN] python-lint: backend venv not found, skipping"
    return 0
  fi

  # Install ruff if not present
  "$venv/bin/python" -m pip install ruff >>"$REPORT_DIR/lint_setup.log" 2>&1 || {
    log_note "[WARN] python-lint: failed to install ruff"
    return 0
  }

  log_note "Running Ruff on backend/, mcp/ …"
  local code=0
  "$venv/bin/python" -m ruff check \
    "$ROOT_DIR/backend/" "$ROOT_DIR/mcp/" \
    --config "$ROOT_DIR/ruff.toml" >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "[CLEAN] No Python lint issues found"
  else
    local issue_count
    issue_count=$(wc -l < "$log" | tr -d ' ')
    log_note "[INFO] Ruff found issues ($issue_count lines) — see python_lint.log (report-only, not failing)"
    # Show a brief summary
    tail -n 20 "$log" | tee -a "$SUMMARY_FILE"
  fi
}

run_frontend_lint() {
  if [[ "$SKIP_LINT" = "1" ]]; then
    log_note "[SKIP] Frontend lint (SKIP_LINT=1)"
    return 0
  fi

  print_header "Frontend Lint (ESLint)"
  local svc_dir="$ROOT_DIR/frontend"
  local log="$REPORT_DIR/frontend_lint.log"

  if [[ ! -d "$svc_dir" ]]; then
    log_note "[WARN] frontend-lint: frontend directory not found"
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    log_note "[WARN] frontend-lint: npm not installed, skipping"
    return 0
  fi

  log_note "Running ESLint on frontend/ …"
  local code=0
  npm --prefix "$svc_dir" run lint >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "[CLEAN] No frontend lint issues found"
  else
    log_note "[INFO] ESLint found issues — see frontend_lint.log (report-only, not failing)"
    tail -n 20 "$log" | tee -a "$SUMMARY_FILE"
  fi
}

# -------- Dependency Scanning --------
run_dependency_scan() {
  if [[ "$SKIP_DEP_SCAN" = "1" ]]; then
    log_note "[SKIP] Dependency scan (SKIP_DEP_SCAN=1)"
    return 0
  fi

  print_header "Dependency Vulnerability Scan"
  local log="$REPORT_DIR/dependency_scan.log"
  local venv="$ROOT_DIR/backend/.venv"

  # Python: pip-audit
  if [[ -d "$venv" ]]; then
    "$venv/bin/python" -m pip install pip-audit >>"$REPORT_DIR/dep_scan_setup.log" 2>&1 || {
      log_note "[WARN] dep-scan: failed to install pip-audit, skipping Python scan"
    }

    if "$venv/bin/python" -m pip_audit --version >/dev/null 2>&1; then
      log_note "Scanning Python dependencies (pip-audit) …"
      for req_file in backend/requirements.txt mcp/requirements.txt; do
        local full_path="$ROOT_DIR/$req_file"
        if [[ -f "$full_path" ]]; then
          echo "--- $req_file ---" >>"$log"
          "$venv/bin/python" -m pip_audit -r "$full_path" >>"$log" 2>&1 || true
          echo "" >>"$log"
        fi
      done
      # Summarize
      local vuln_count
      vuln_count=$(grep -c "VULN" "$log" 2>/dev/null || echo "0")
      if [[ "$vuln_count" -gt 0 ]]; then
        log_note "[INFO] pip-audit found $vuln_count vulnerability(ies) — see dependency_scan.log (report-only)"
      else
        log_note "[CLEAN] No Python dependency vulnerabilities found"
      fi
    fi
  else
    log_note "[WARN] dep-scan: backend venv not found, skipping Python scan"
  fi

  # Node.js: npm audit
  local npm_log="$REPORT_DIR/npm_audit.log"
  if command -v npm >/dev/null 2>&1 && [[ -d "$ROOT_DIR/frontend" ]]; then
    log_note "Scanning Node.js dependencies (npm audit) …"
    npm audit --prefix "$ROOT_DIR/frontend" >"$npm_log" 2>&1 || true
    if grep -q "found 0 vulnerabilities" "$npm_log" 2>/dev/null; then
      log_note "[CLEAN] No Node.js dependency vulnerabilities found"
    else
      log_note "[INFO] npm audit found issues — see npm_audit.log (report-only)"
      tail -n 10 "$npm_log" | tee -a "$SUMMARY_FILE"
    fi
  else
    log_note "[WARN] dep-scan: npm or frontend directory not found, skipping Node.js scan"
  fi
}

# -------- Test Runners --------
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

# extraction-service tests removed — extraction now handled by curatore-document-service

run_mcp_tests() {
  local svc="mcp"
  local svc_dir="$ROOT_DIR/mcp"
  local subdir="$REPORT_DIR/$svc"
  mkdir -p "$subdir"
  local log="$subdir/${svc}.log"

  if [[ ! -d "$svc_dir" ]]; then
    log_note "[WARN] $svc: directory not found"
    record_result "$svc" "WARN" "directory not found"
    return 0
  fi

  # ensure_python_venv mixes log output with the venv path on stdout,
  # so use the known path directly instead of capturing output.
  ensure_python_venv "$svc" "$svc_dir" "$svc_dir/requirements.txt" "3.12" >/dev/null || {
    record_result "$svc" "WARN" "venv setup failed"
    return 0
  }
  local venv="$svc_dir/.venv"

  # Build coverage flags
  local cov_flags=()
  if [[ "$SKIP_COVERAGE" != "1" ]]; then
    cov_flags=(--cov=app --cov-report=term-missing --cov-report=html:"$subdir/mcp_coverage_html")
  fi

  log_note "Running $svc tests (pytest) …"
  local code=0
  (
    cd "$svc_dir" && \
    MCP_API_KEY="test-key" BACKEND_URL="http://localhost:8000" \
    PYTHONPATH="${svc_dir}${PYTHONPATH:+:$PYTHONPATH}" \
    "$venv/bin/python" -m pytest tests -q "${cov_flags[@]}"
  ) >"$log" 2>&1 || code=$?

  # Surface results
  if [[ -f "$log" ]]; then
    res_line=$(grep -E "[0-9]+ passed" "$log" | tail -n 1 || true)
    [[ -n "$res_line" ]] && log_note "$res_line"
  fi

  if [[ $code -eq 0 ]]; then
    log_note "[PASS] $svc"
    record_result "$svc" "PASS"
  else
    log_note "[FAIL] $svc (exit $code) — see $(basename "$log")"
    show_log_tail "$log" "$svc test failure"
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
    if [[ "$SKIP_COVERAGE" != "1" ]]; then
      cmd=(pnpm -C "$svc_dir" -s test -- --coverage)
    else
      cmd=(pnpm -C "$svc_dir" -s test)
    fi
  elif [[ -f "$svc_dir/yarn.lock" ]] && command -v yarn >/dev/null 2>&1; then
    runner="yarn"
    if [[ "$SKIP_COVERAGE" != "1" ]]; then
      cmd=(yarn --cwd "$svc_dir" test -s -- --coverage)
    else
      cmd=(yarn --cwd "$svc_dir" test -s)
    fi
  else
    runner="npm"
    if ! command -v npm >/dev/null 2>&1; then
      echo "[WARN] $svc: npm not installed" | tee -a "$SUMMARY_FILE"
      record_result "$svc" "WARN" "npm missing"
      return 0
    fi
    if [[ "$SKIP_COVERAGE" != "1" ]]; then
      cmd=(npm --prefix "$svc_dir" run -s test --if-present -- --coverage)
    else
      cmd=(npm --prefix "$svc_dir" run -s test --if-present)
    fi
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
echo "Skip lint: ${SKIP_LINT}, Skip coverage: ${SKIP_COVERAGE}, Skip dep scan: ${SKIP_DEP_SCAN}" | tee -a "$SUMMARY_FILE"

# Lint first (fast feedback)
run_python_lint
run_frontend_lint

# Dependency scanning
run_dependency_scan

# Then tests
run_backend_tests
run_mcp_tests
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
