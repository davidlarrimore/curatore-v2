#!/usr/bin/env bash
# ==============================================================================
# Curatore v2 — Project Initialization
# ------------------------------------------------------------------------------
# What this does:
#  1) Verifies Docker is running and selects the right compose CLI.
#  2) Ensures the canonical host directory tree exists:
#       ./files/{uploaded_files,processed_files,batch_files}
#  3) Makes utility scripts executable.
#  4) Bootstraps a .env from .env.example if missing.
#  5) Validates docker-compose configuration.
#  6) Builds images. (Optionally starts services with --up)
#  7) Writes a guard file to prevent accidental re-runs.
#
# Usage:
#   ./scripts/init.sh          # prepare & build
#   ./scripts/init.sh --up     # prepare, build, and start
#   ./scripts/init.sh --force  # bypass guard and re-run initialization
#
# If this project has already been initialized, this script will refuse to run
# and suggest using ./scripts/nuke.sh to fully reset the environment.
# ==============================================================================

set -euo pipefail

# --- Resolve repo root regardless of where the script is invoked from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GUARD_FILE="${REPO_ROOT}/.curatore_initialized"

echo "🧭 Repo root: ${REPO_ROOT}"

# --- Parse flags
START_AFTER_BUILD=false
FORCE_REINIT=false
for arg in "${@:-}"; do
  case "${arg}" in
    --up|--start) START_AFTER_BUILD=true ;;
    --force)      FORCE_REINIT=true ;;
    *) echo "⚠️  Unknown argument: ${arg} (ignored)";;
  esac
done

# --- Guard: prevent accidental re-runs unless --force
if [[ -f "${GUARD_FILE}" && "${FORCE_REINIT}" != "true" ]]; then
  echo "⛔ Detected prior initialization (${GUARD_FILE})."
  echo "   If you need a clean slate, run: ./scripts/nuke.sh"
  echo "   To bypass and re-run init anyway: ./scripts/init.sh --force"
  exit 2
fi

# --- Pick compose command (docker compose vs docker-compose)
pick_compose() {
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    echo "docker compose"
  elif command -v docker-compose &>/dev/null; then
    echo "docker-compose"
  else
    echo ""
  fi
}

# --- Verify Docker daemon is up
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

# --- Ensure helper scripts are executable
if compgen -G "${REPO_ROOT}/scripts/*.sh" > /dev/null; then
  chmod +x "${REPO_ROOT}"/scripts/*.sh || true
fi

# --- Ensure canonical directory structure exists (host-level)
if [[ -x "${REPO_ROOT}/scripts/setup_directories.sh" ]]; then
  "${REPO_ROOT}/scripts/setup_directories.sh"
else
  echo "ℹ️  setup-directories.sh not found; creating minimal structure directly..."
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

# --- Scaffold .env from example if missing
if [[ ! -f "${REPO_ROOT}/.env" && -f "${REPO_ROOT}/.env.example" ]]; then
  cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
  echo "🧪 Created .env from .env.example"
fi

# --- Validate compose file
echo "🔎 Validating docker-compose configuration..."
${DC} -f "${REPO_ROOT}/docker-compose.yml" config >/dev/null
echo "✅ docker-compose.yml looks good."

# --- Build images
echo "🏗️ Building images (this can take a bit the first time)..."
${DC} -f "${REPO_ROOT}/docker-compose.yml" build
echo "✅ Build complete."

# --- Optionally start the stack
if [[ "${START_AFTER_BUILD}" == "true" ]]; then
  echo "🚀 Starting Curatore v2 stack..."
  ${DC} -f "${REPO_ROOT}/docker-compose.yml" up -d
  echo "🌐 Frontend: http://localhost:3000"
  echo "🔗 Backend:  http://localhost:8000 (Swagger at /docs)"
else
  echo "ℹ️  To start the dev stack now, run: ./scripts/dev-up.sh  (or ./scripts/init.sh --up)"
fi

# --- Write/refresh guard file
COMPOSE_HASH="$(sha1sum "${REPO_ROOT}/docker-compose.yml" | awk '{print $1}')"
ENV_HASH="$(test -f "${REPO_ROOT}/.env" && sha1sum "${REPO_ROOT}/.env" | awk '{print $1}' || echo "no-env")"
DATE_ISO="$(date -Iseconds 2>/dev/null || date)"

cat > "${GUARD_FILE}" <<EOF
initialized_at="${DATE_ISO}"
compose_hash="${COMPOSE_HASH}"
env_hash="${ENV_HASH}"
by="$(whoami 2>/dev/null || echo unknown)"
EOF

echo ""
echo "📁 Host storage root: ${REPO_ROOT}/files"
echo "   ├─ uploaded_files/   (UI/API uploads)"
echo "   ├─ processed_files/  (markdown outputs)"
echo "   └─ batch_files/      (manual batch inputs)"
echo ""
echo "✅ Initialization complete. Guard written to: ${GUARD_FILE}"
