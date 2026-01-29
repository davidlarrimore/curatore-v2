#!/usr/bin/env bash
#
# Storage Cleanup Helper Script
#
# Convenience wrapper for the cleanup_storage command.
# Run this when making breaking changes to the storage layer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT/backend"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo ""
echo -e "${RED}⚠️  STORAGE CLEANUP UTILITY${NC}"
echo ""

# Check if --help flag is present
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --dry-run           Show what would be deleted without deleting"
    echo "  --force             Skip confirmation prompt"
    echo "  --skip-recreate     Skip bucket recreation after cleanup"
    echo "  --org-id UUID       Limit to specific organization"
    echo "  --bucket NAME       Limit to specific bucket"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --dry-run                    # See what would be deleted"
    echo "  $0                              # Interactive cleanup (with confirmation)"
    echo "  $0 --force                      # Cleanup without confirmation"
    echo "  $0 --bucket curatore-uploads    # Clean only uploads bucket"
    echo "  $0 --skip-recreate              # Cleanup only (no bucket recreation)"
    echo ""
    exit 0
fi

# Check if virtual environment exists
if [[ ! -d ".venv" ]]; then
    echo -e "${RED}Error: Virtual environment not found at backend/.venv${NC}"
    echo "Run: cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Check if dry-run mode
if [[ "${1:-}" == "--dry-run" ]]; then
    echo -e "${YELLOW}Running in DRY RUN mode (no changes will be made)${NC}"
    echo ""
fi

# Run the cleanup command
python -m app.commands.cleanup_storage "$@"

echo ""
echo -e "${GREEN}Done!${NC}"
