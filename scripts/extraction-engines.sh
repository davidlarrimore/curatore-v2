#!/usr/bin/env bash
#
# Helper to normalize the extraction engine selection so every tool
# (Makefile, dev-up script, CI, etc.) derives the same Compose profiles.
#
# Usage:
#   scripts/extraction-engines.sh list    # → "default docling"
#   scripts/extraction-engines.sh extras  # → "docling"
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

trim() {
  sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

load_raw_engines() {
  local raw="${EXTRACTION_ENGINES:-}"
  if [[ -z "${raw}" && -f "${ENV_FILE}" ]]; then
    raw="$(sed -n 's/^EXTRACTION_ENGINES=\(.*\)$/\1/p' "${ENV_FILE}" | tail -n1)"
  fi
  if [[ -z "${raw}" ]]; then
    raw="default"
  fi
  printf '%s' "${raw}" | trim
}

normalize_engines() {
  local raw="$1"
  raw="${raw//\"/}"
  raw="${raw//\'/}"
  raw="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]')"
  raw="${raw//,/ }"
  raw="${raw//;/ }"

  local token
  local engines=""
  for token in $raw; do
    [[ -z "${token}" ]] && continue
    if [[ "${token}" == "default" ]]; then
      case " ${engines} " in
        *" default "*) ;;
        *)
          if [[ -z "${engines}" ]]; then
            engines="default"
          else
            engines="default ${engines}"
          fi
          ;;
      esac
      continue
    fi
    case " ${engines} " in
      *" ${token} "*) ;;
      *)
        if [[ -z "${engines}" ]]; then
          engines="${token}"
        else
          engines="${engines} ${token}"
        fi
        ;;
    esac
  done

  case " ${engines} " in
    *" default "*) ;;
    *)
      if [[ -z "${engines}" ]]; then
        engines="default"
      else
        engines="default ${engines}"
      fi
      ;;
  esac

  printf '%s' "${engines}"
}

main() {
  local action="${1:-list}"
  local engines
  engines="$(normalize_engines "$(load_raw_engines)")"

  case "${action}" in
    list)
      printf '%s\n' "${engines}"
      ;;
    extras)
      local extra_out=""
      local token
      for token in ${engines}; do
        [[ "${token}" == "default" ]] && continue
        if [[ -z "${extra_out}" ]]; then
          extra_out="${token}"
        else
          extra_out="${extra_out} ${token}"
        fi
      done
      printf '%s\n' "${extra_out}"
      ;;
    *)
      echo "Usage: $0 {list|extras}" >&2
      exit 64
      ;;
  esac
}

main "$@"
