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

# Read ENABLE_DOCLING_SERVICE from .env (default: false)
ENABLE_FLAG="false"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  # Extract last defined value, trim quotes and spaces, lowercase
  ENABLE_FLAG="$(sed -n 's/^ENABLE_DOCLING_SERVICE=\(.*\)$/\1/p' "${REPO_ROOT}/.env" | tail -n1 | tr -d '"' | tr '[:upper:]' '[:lower:]')"
fi

# Prefer Makefile helper to honor ENABLE_DOCLING_SERVICE toggle
if command -v make >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/Makefile" ]]; then
  echo "🛠  Using Makefile (ENABLE_DOCLING_SERVICE=${ENABLE_FLAG})"
  ENABLE_DOCLING_SERVICE="${ENABLE_FLAG}" make -C "${REPO_ROOT}" up
else
  echo "ℹ️  Make not available; falling back to docker compose"
  if [[ "${ENABLE_FLAG}" == "true" ]]; then
    ${DC} -f "${REPO_ROOT}/docker-compose.yml" --profile docling up -d --build
  else
    ${DC} -f "${REPO_ROOT}/docker-compose.yml" up -d --build
  fi
fi

echo "🌐 Frontend: http://localhost:3000"
echo "🔗 Backend:  http://localhost:8000 (Swagger at /docs)"
