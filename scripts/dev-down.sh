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

echo "🛑 Stopping Curatore v2 development environment..."

# Prefer Makefile to ensure profile-based services (docling) are also torn down
if command -v make >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/Makefile" ]]; then
  echo "🛠  Using Makefile to stop stack (handles docling profile)"
  make -C "${REPO_ROOT}" down
else
  echo "ℹ️  Make not available; using docker compose directly"
  # Run down twice: once with docling profile (if it was used), then general down
  ${DC} -f "${REPO_ROOT}/docker-compose.yml" --profile docling down --remove-orphans || true
  ${DC} -f "${REPO_ROOT}/docker-compose.yml" down --remove-orphans
fi
