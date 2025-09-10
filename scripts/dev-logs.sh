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

if [[ $# -gt 0 ]]; then
  # Tail specific services passed as args
  exec ${DC} -f "${REPO_ROOT}/docker-compose.yml" logs -f "$@"
else
  # Tail all services
  exec ${DC} -f "${REPO_ROOT}/docker-compose.yml" logs -f
fi

