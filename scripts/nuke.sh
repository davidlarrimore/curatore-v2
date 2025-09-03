#!/usr/bin/env bash
# ==============================================================================
# Curatore v2 — Full Reset ("NUKE")
# ------------------------------------------------------------------------------
# What this does:
#  1) Confirms destructive reset (use --yes to skip prompt).
#  2) Verifies Docker/Compose availability.
#  3) Stops & removes containers, volumes, and orphans.
#  4) Cleans local caches (Python/Node), virtualenvs, and project artifacts.
#  5) Resets ./files content but preserves directory structure & .gitkeep.
#  6) Optionally prunes dangling images (--prune-images).
#  7) Re-creates storage structure (setup-directories.sh).
#  8) Re-runs init.sh (optionally with --up).
#
# Usage:
#   ./scripts/nuke.sh
#   ./scripts/nuke.sh --yes --prune-images --up
#
# Notes:
# - By default, keeps your .env. Use --purge-env to delete it.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GUARD_FILE="${REPO_ROOT}/.curatore_initialized"

CONFIRM="ask"
PRUNE_IMAGES="no"
START_AFTER_RESET="no"
PURGE_ENV="no"

for arg in "${@:-}"; do
  case "${arg}" in
    --yes)           CONFIRM="yes" ;;
    --prune-images)  PRUNE_IMAGES="yes" ;;
    --up|--start)    START_AFTER_RESET="yes" ;;
    --purge-env)     PURGE_ENV="yes" ;;
    *)
      echo "⚠️  Unknown argument: ${arg} (ignored)";;
  esac
done

# --- Confirmation
if [[ "${CONFIRM}" != "yes" ]]; then
  echo "⚠️  This will STOP and REMOVE containers, volumes, local build artifacts,"
  echo "    and CLEAR ./files contents. Continue? [y/N]"
  read -r answer
  case "${answer:-N}" in
    y|Y|yes|YES) ;;
    *) echo "❎ Aborted."; exit 0;;
  esac
fi

# --- Compose picker & Docker checks (same helpers as init.sh)
pick_compose() {
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    echo "docker compose"
  elif command -v docker-compose &>/dev/null; then
    echo "docker-compose"
  else
    echo ""
  fi
}

if ! command -v docker &>/dev/null; then
  echo "❌ Docker not found. Please install Docker Desktop."
  exit 1
fi
if ! docker info &>/dev/null; then
  echo "❌ Docker daemon not reachable. Start Docker Desktop and retry."
  exit 1
fi
DC="$(pick_compose)"
if [[ -z "${DC}" ]]; then
  echo "❌ Neither 'docker compose' nor 'docker-compose' found."
  exit 1
fi
echo "🐳 Using compose CLI: ${DC}"

# --- Stop & remove stack (ignore failures for idempotency)
echo "🛑 Stopping/removing stack..."
${DC} -f "${REPO_ROOT}/docker-compose.yml" down -v --remove-orphans || true

# --- Optional prune of dangling images (safe; no in-use images removed)
if [[ "${PRUNE_IMAGES}" == "yes" ]]; then
  echo "🧹 Pruning dangling images..."
  docker image prune -f || true
fi

# --- Clean local caches/artifacts
echo "🧽 Cleaning local caches and artifacts..."
# Python caches
find "${REPO_ROOT}" -type d -name "__pycache__" -prune -exec rm -rf {} + || true
find "${REPO_ROOT}" -type d -name ".pytest_cache" -prune -exec rm -rf {} + || true
# Python virtual environments
rm -rf "${REPO_ROOT}/.venv" || true
rm -rf "${REPO_ROOT}/backend/.venv" || true
rm -rf "${REPO_ROOT}/extraction-service/.venv" || true
# Catch any others nested in submodules/packages
find "${REPO_ROOT}" -type d -name ".venv" -prune -exec rm -rf {} + || true
# Node caches
rm -rf "${REPO_ROOT}/frontend/node_modules" || true
rm -rf "${REPO_ROOT}/frontend/.next" || true
# Logs
find "${REPO_ROOT}" -type f -name "*.log" -delete || true

# --- Reset storage content but keep structure and .gitkeep
echo "🗄️  Resetting ./files contents..."
for sub in uploaded_files processed_files batch_files; do
  dir="${REPO_ROOT}/files/${sub}"
  if [[ -d "${dir}" ]]; then
    find "${dir}" -mindepth 1 -maxdepth 1 ! -name ".gitkeep" -exec rm -rf {} + || true
  fi
done

# --- Optionally purge .env (fresh start)
if [[ "${PURGE_ENV}" == "yes" && -f "${REPO_ROOT}/.env" ]]; then
  echo "🧯 Removing .env (requested via --purge-env)..."
  rm -f "${REPO_ROOT}/.env"
fi

# --- Remove init guard
if [[ -f "${GUARD_FILE}" ]]; then
  echo "🔁 Removing init guard ${GUARD_FILE}..."
  rm -f "${GUARD_FILE}"
fi

# --- Recreate directory structure
if [[ -x "${REPO_ROOT}/scripts/setup_directories.sh" ]]; then
  "${REPO_ROOT}/scripts/setup_directories.sh"
else
  mkdir -p "${REPO_ROOT}/files/uploaded_files" \
           "${REPO_ROOT}/files/processed_files" \
           "${REPO_ROOT}/files/batch_files"
  touch "${REPO_ROOT}/files/uploaded_files/.gitkeep" \
        "${REPO_ROOT}/files/processed_files/.gitkeep" \
        "${REPO_ROOT}/files/batch_files/.gitkeep"
  chmod 755 "${REPO_ROOT}/files" \
            "${REPO_ROOT}/files/uploaded_files" \
            "${REPO_ROOT}/files/processed_files" \
            "${REPO_ROOT}/files/batch_files"
fi

# --- Quick environment sanity checks before re-init
echo "🩺 Sanity checks..."
# Disk space (warn if < 2GB free)
FREE_KB="$(df -Pk "${REPO_ROOT}" | awk 'NR==2{print $4}')"
if [[ -n "${FREE_KB}" && "${FREE_KB}" -lt 2000000 ]]; then
  echo "⚠️  Low disk space (<2GB free). Builds may fail."
fi

# Port availability hints (non-fatal)
for port in 3000 8000 6379; do
  if lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null | grep -q ":${port} "; then
    echo "⚠️  Port ${port} appears to be in use. The stack may fail to start."
  fi
done

# --- Re-run init.sh (optionally start services)
echo "🔁 Re-initializing project..."
if [[ "${START_AFTER_RESET}" == "yes" ]]; then
  "${REPO_ROOT}/scripts/init.sh" --up
else
  "${REPO_ROOT}/scripts/init.sh"
fi

echo "✅ Nuke/reset complete."
