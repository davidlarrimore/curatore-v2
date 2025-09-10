#!/usr/bin/env bash
# ============================================================================
# Curatore v2 - Setup local directory structure
# Creates the host-level "./files" tree so Docker bind mounts work reliably.
# Run any time; safe to re-run.
# ============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🔧 Creating Curatore v2 directory structure under ${ROOT_DIR}/files"

mkdir -p "${ROOT_DIR}/files/uploaded_files"
mkdir -p "${ROOT_DIR}/files/processed_files"
mkdir -p "${ROOT_DIR}/files/batch_files"

# Keep empty dirs in git
touch "${ROOT_DIR}/files/uploaded_files/.gitkeep"
touch "${ROOT_DIR}/files/processed_files/.gitkeep"
touch "${ROOT_DIR}/files/batch_files/.gitkeep"

# Reasonable POSIX permissions
chmod 755 "${ROOT_DIR}/files" \
          "${ROOT_DIR}/files/uploaded_files" \
          "${ROOT_DIR}/files/processed_files" \
          "${ROOT_DIR}/files/batch_files"

echo "✅ Done."
echo "   files/"
echo "     ├─ uploaded_files/"
echo "     ├─ processed_files/"
echo "     └─ batch_files/"
