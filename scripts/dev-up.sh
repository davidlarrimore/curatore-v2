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

# Shared helper to keep Makefile/dev scripts in sync
ENGINE_HELPER="${REPO_ROOT}/scripts/extraction-engines.sh"
ENGINES="$("${ENGINE_HELPER}" list)"
EXTRA_ENGINES="$("${ENGINE_HELPER}" extras)"
PROFILE_FLAGS=""
for eng in ${EXTRA_ENGINES}; do
  PROFILE_FLAGS="${PROFILE_FLAGS} --profile ${eng}"
done

echo "⚙️  Extraction engines: ${ENGINES:-default}"

# Prefer Makefile helper which uses the same helper script
if command -v make >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/Makefile" ]]; then
  echo "🛠  Using Makefile to start the stack"
  make -C "${REPO_ROOT}" up
else
  echo "ℹ️  Make not available; falling back to docker compose"
  ${DC} -f "${REPO_ROOT}/docker-compose.yml" ${PROFILE_FLAGS} up -d --build
fi

echo "🌐 Frontend: http://localhost:3000"
echo "🔗 Backend:  http://localhost:8000 (Swagger at /docs)"
