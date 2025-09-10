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

BUILD=false
SERVICES=()

for arg in "$@"; do
  case "${arg}" in
    --build) BUILD=true ;;
    *) SERVICES+=("${arg}") ;;
  esac
done

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  # Default to worker if no service specified
  SERVICES=(worker)
fi

if [[ "${BUILD}" == "true" ]]; then
  echo "🔁 Rebuilding and restarting: ${SERVICES[*]}"
  ${DC} -f "${REPO_ROOT}/docker-compose.yml" build "${SERVICES[@]}"
  exec ${DC} -f "${REPO_ROOT}/docker-compose.yml" up -d "${SERVICES[@]}"
else
  echo "🔁 Restarting: ${SERVICES[*]}"
  exec ${DC} -f "${REPO_ROOT}/docker-compose.yml" restart "${SERVICES[@]}"
fi

