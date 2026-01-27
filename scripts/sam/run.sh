#!/bin/bash
# =============================================================================
# SAM.gov Pull Script Runner
# =============================================================================
# Automatically handles Python environment setup and runs sam_pull.py
#
# Usage:
#   ./scripts/sam/run.sh           # Run from project root (recommended)
#   bash scripts/sam/run.sh        # Explicit bash invocation
#   ./run.sh                        # Run from scripts/sam/ directory
#
# DO NOT USE: sh scripts/sam/run.sh (will not work correctly)
#
# Requirements:
#   - Python 3.12+ installed
#   - backend/requirements.txt dependencies
# =============================================================================

# Check if running with bash
if [ -z "$BASH_VERSION" ]; then
    echo "Error: This script requires bash, but you're running it with sh or another shell."
    echo ""
    echo "Please run it one of these ways:"
    echo "  ./scripts/sam/run.sh         (recommended)"
    echo "  bash scripts/sam/run.sh      (explicit bash)"
    echo ""
    echo "DO NOT USE: sh scripts/sam/run.sh"
    exit 1
fi

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the project root directory (2 levels up from this script)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

echo "=================================================================================="
echo "SAM.gov Pull Script Runner"
echo "=================================================================================="
echo ""

# =============================================================================
# Function to check if command exists
# =============================================================================
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# =============================================================================
# Function to check Python version
# =============================================================================
check_python_version() {
    local python_cmd=$1
    if command_exists "$python_cmd"; then
        local version=$($python_cmd --version 2>&1 | awk '{print $2}')
        local major=$(echo "$version" | cut -d. -f1)
        local minor=$(echo "$version" | cut -d. -f2)

        # Check if Python 3.12 or 3.13 (3.14 is too new)
        if [ "$major" = "3" ] && [ "$minor" -ge "12" ] && [ "$minor" -le "13" ]; then
            echo "$python_cmd"
            return 0
        fi
    fi
    return 1
}

# =============================================================================
# Find suitable Python installation
# =============================================================================
echo -e "${BLUE}Step 1: Finding Python 3.12 or 3.13...${NC}"

PYTHON_CMD=""

# Try common Python commands in order of preference
for cmd in python3.12 python3.13 python3 python; do
    if check_python_version "$cmd"; then
        PYTHON_CMD=$cmd
        PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
        echo -e "${GREEN}✓ Found compatible Python: $PYTHON_CMD ($PYTHON_VERSION)${NC}"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}✗ Error: Python 3.12 or 3.13 not found${NC}"
    echo ""
    echo "Please install Python 3.12:"
    echo "  brew install python@3.12"
    echo ""
    exit 1
fi

echo ""

# =============================================================================
# Check for virtual environment
# =============================================================================
echo -e "${BLUE}Step 2: Setting up Python environment...${NC}"

# Check if backend venv exists and has compatible Python
if [ -d "backend/venv" ]; then
    BACKEND_PYTHON="backend/venv/bin/python"
    if [ -f "$BACKEND_PYTHON" ]; then
        BACKEND_VERSION=$($BACKEND_PYTHON --version 2>&1 | awk '{print $2}')
        BACKEND_MAJOR=$(echo "$BACKEND_VERSION" | cut -d. -f1)
        BACKEND_MINOR=$(echo "$BACKEND_VERSION" | cut -d. -f2)

        if [ "$BACKEND_MAJOR" = "3" ] && [ "$BACKEND_MINOR" -ge "12" ] && [ "$BACKEND_MINOR" -le "13" ]; then
            echo -e "${GREEN}✓ Using backend virtual environment ($BACKEND_VERSION)${NC}"
            PYTHON_CMD="$BACKEND_PYTHON"
        else
            echo -e "${YELLOW}⚠ Backend venv has Python $BACKEND_VERSION (need 3.12-3.13)${NC}"
        fi
    fi
fi

# If not using backend venv, check for .venv in project root
if [ "$PYTHON_CMD" != "backend/venv/bin/python" ]; then
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}⚠ No virtual environment found at .venv${NC}"
        echo -e "${BLUE}Creating new virtual environment...${NC}"

        # Find the base Python command again (not venv)
        BASE_PYTHON=""
        for cmd in python3.12 python3.13 python3; do
            if check_python_version "$cmd"; then
                BASE_PYTHON=$cmd
                break
            fi
        done

        $BASE_PYTHON -m venv .venv
        echo -e "${GREEN}✓ Created .venv${NC}"
    fi

    # Check if .venv has compatible Python
    if [ -f ".venv/bin/python" ]; then
        VENV_VERSION=$(.venv/bin/python --version 2>&1 | awk '{print $2}')
        VENV_MAJOR=$(echo "$VENV_VERSION" | cut -d. -f1)
        VENV_MINOR=$(echo "$VENV_VERSION" | cut -d. -f2)

        if [ "$VENV_MAJOR" = "3" ] && [ "$VENV_MINOR" -ge "12" ] && [ "$VENV_MINOR" -le "13" ]; then
            echo -e "${GREEN}✓ Using project virtual environment ($VENV_VERSION)${NC}"
            PYTHON_CMD=".venv/bin/python"
        else
            echo -e "${RED}✗ Error: .venv has incompatible Python $VENV_VERSION${NC}"
            echo "Please recreate .venv with Python 3.12:"
            echo "  rm -rf .venv"
            echo "  python3.12 -m venv .venv"
            exit 1
        fi
    fi
fi

echo ""

# =============================================================================
# Check/Install dependencies
# =============================================================================
echo -e "${BLUE}Step 3: Checking dependencies...${NC}"

# Check if requests module is installed
if ! $PYTHON_CMD -c "import requests" 2>/dev/null; then
    echo -e "${YELLOW}⚠ Dependencies not installed${NC}"
    echo -e "${BLUE}Installing dependencies from backend/requirements.txt...${NC}"

    # Get pip for the selected Python
    if [[ "$PYTHON_CMD" == *"/bin/python"* ]]; then
        PIP_CMD="${PYTHON_CMD%python}pip"
    else
        PIP_CMD="$PYTHON_CMD -m pip"
    fi

    $PIP_CMD install -r backend/requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
else
    echo -e "${GREEN}✓ Dependencies already installed${NC}"
fi

echo ""

# =============================================================================
# Verify environment variables
# =============================================================================
echo -e "${BLUE}Step 4: Checking environment variables...${NC}"

# Load .env if it exists (only valid KEY=VALUE pairs)
if [ -f ".env" ]; then
    # Use POSIX-compliant approach that works with both sh and bash
    while IFS='=' read -r key value || [ -n "$key" ]; do
        # Skip empty lines and comments
        case "$key" in
            ''|'#'*) continue ;;
        esac
        # Only export valid environment variable names (uppercase letters, numbers, underscores)
        case "$key" in
            [A-Z_]*) export "$key=$value" ;;
        esac
    done < .env
fi

MISSING_VARS=0

if [ -z "$SAM_API_KEY" ]; then
    echo -e "${RED}✗ SAM_API_KEY not set${NC}"
    MISSING_VARS=1
fi

if [ -z "$DEFAULT_ORG_ID" ]; then
    echo -e "${RED}✗ DEFAULT_ORG_ID not set${NC}"
    MISSING_VARS=1
fi

if [ $MISSING_VARS -eq 1 ]; then
    echo ""
    echo "Please add missing variables to .env file:"
    echo "  SAM_API_KEY=your-sam-gov-api-key"
    echo "  DEFAULT_ORG_ID=your-org-uuid"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ SAM_API_KEY configured${NC}"
echo -e "${GREEN}✓ DEFAULT_ORG_ID configured${NC}"

echo ""

# =============================================================================
# Run the script
# =============================================================================
echo "=================================================================================="
echo "Running SAM.gov Pull Script"
echo "=================================================================================="
echo ""

exec $PYTHON_CMD scripts/sam/sam_pull.py "$@"
