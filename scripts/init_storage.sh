#!/bin/bash
# Initialize object storage (create buckets, set lifecycle policies)

set -e

echo "=========================================="
echo "Initializing Object Storage"
echo "=========================================="
echo ""

# Check if backend container is running
if ! docker ps | grep -q curatore-backend; then
    echo "ERROR: Backend container (curatore-backend) is not running"
    echo "Start services first with: ./scripts/dev-up.sh"
    exit 1
fi

# Run initialization command
docker exec curatore-backend python -m app.core.commands.init_storage "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✓ Object storage initialized successfully"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "✗ Object storage initialization failed"
    echo "=========================================="
    exit $exit_code
fi
