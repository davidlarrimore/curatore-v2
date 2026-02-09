#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root regardless of invocation path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

pick_compose() {
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    echo "docker compose"
  elif command -v docker-compose &>/dev/null; then
    echo "docker-compose"
  else
    echo ""
  fi
}

DC="$(pick_compose)"
if [[ -z "${DC}" ]]; then
  echo "❌ Neither 'docker compose' nor 'docker-compose' found."
  exit 1
fi

echo "🚀 Starting Curatore v2 development environment..."
# Ensure helper scripts are executable
if compgen -G "${REPO_ROOT}/scripts/*.sh" > /dev/null; then
  chmod +x "${REPO_ROOT}"/scripts/*.sh || true
fi

# Read feature flags from .env (defaults)
ENABLE_DOCLING="false"
ENABLE_POSTGRES="true"  # PostgreSQL is enabled by default (required)

if [[ -f "${REPO_ROOT}/.env" ]]; then
  # Extract ENABLE_DOCLING_SERVICE
  ENABLE_DOCLING="$(sed -n 's/^ENABLE_DOCLING_SERVICE=\(.*\)$/\1/p' "${REPO_ROOT}/.env" | tail -n1 | tr -d '"' | tr '[:upper:]' '[:lower:]')"
  # Extract ENABLE_POSTGRES_SERVICE
  ENABLE_POSTGRES="$(sed -n 's/^ENABLE_POSTGRES_SERVICE=\(.*\)$/\1/p' "${REPO_ROOT}/.env" | tail -n1 | tr -d '"' | tr '[:upper:]' '[:lower:]')"
fi

# Default empty values
ENABLE_DOCLING="${ENABLE_DOCLING:-false}"
ENABLE_POSTGRES="${ENABLE_POSTGRES:-true}"

# Prefer Makefile helper to honor feature toggles
if command -v make >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/Makefile" ]]; then
  echo "🛠  Using Makefile"
  echo "   ENABLE_POSTGRES_SERVICE=${ENABLE_POSTGRES}"
  echo "   ENABLE_DOCLING_SERVICE=${ENABLE_DOCLING}"
  echo "   MinIO (Object Storage): REQUIRED - starts automatically"
  ENABLE_POSTGRES_SERVICE="${ENABLE_POSTGRES}" ENABLE_DOCLING_SERVICE="${ENABLE_DOCLING}" make -C "${REPO_ROOT}" up
else
  echo "ℹ️  Make not available; falling back to docker compose"
  echo "   MinIO (Object Storage): REQUIRED - starts automatically"

  # Build profiles list
  PROFILES=""
  if [[ "${ENABLE_POSTGRES}" == "true" ]]; then
    PROFILES="${PROFILES} --profile postgres"
    echo "   🐘 PostgreSQL profile enabled"
  fi
  if [[ "${ENABLE_DOCLING}" == "true" ]]; then
    PROFILES="${PROFILES} --profile docling"
    echo "   📦 Docling profile enabled"
  fi

  ${DC} -f "${REPO_ROOT}/docker-compose.yml" ${PROFILES} up -d --build
fi

echo ""
echo "✅ Services started successfully!"
echo ""
echo "🌐 Frontend:    http://localhost:3000"
echo "🔗 Backend:     http://localhost:8000 (Swagger at /docs)"
echo "📦 Extraction:  http://localhost:8010 (Swagger at /api/v1/docs)"
echo "🤖 MCP Gateway: http://localhost:8020 (Open WebUI integration)"
echo "🪣 MinIO:       http://localhost:9001 (Console - admin/changeme)"
if [[ "${ENABLE_POSTGRES}" == "true" ]]; then
  echo "🐘 PostgreSQL:  localhost:5432 (curatore/curatore_dev_password)"
fi
if [[ "${ENABLE_DOCLING}" == "true" ]]; then
  echo "📄 Docling:     http://localhost:5151"
fi
echo ""
echo "⏳ Initializing object storage..."
"${REPO_ROOT}/scripts/init_storage.sh" || {
  echo "⚠️  Object storage initialization failed (this is normal on first run)"
  echo "   MinIO may still be starting up. Run './scripts/init_storage.sh' manually after a few seconds."
}
