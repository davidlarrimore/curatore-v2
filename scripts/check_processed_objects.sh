#!/bin/bash

# Quick script to check processed objects in MinIO

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
API_BASE="${BACKEND_URL}/api/v1"

echo "=== Checking Processed Files ==="
echo ""

# Get auth token (you'll need to set this)
if [ -z "$TOKEN" ]; then
    echo "❌ Please set TOKEN environment variable with your JWT token"
    echo ""
    echo "Example:"
    echo "  export TOKEN=\"your-jwt-token-here\""
    echo "  ./scripts/check_processed_objects.sh"
    echo ""
    exit 1
fi

echo "1. Checking storage health..."
curl -s -H "Authorization: Bearer $TOKEN" \
    "${API_BASE}/storage/health" | python3 -m json.tool
echo ""
echo ""

echo "2. Listing buckets..."
curl -s -H "Authorization: Bearer $TOKEN" \
    "${API_BASE}/storage/buckets" | python3 -m json.tool
echo ""
echo ""

echo "3. Browsing curatore-processed bucket (root)..."
curl -s -H "Authorization: Bearer $TOKEN" \
    "${API_BASE}/storage/browse?bucket=curatore-processed&prefix=" | python3 -m json.tool
echo ""
echo ""

echo "Done!"
echo ""
echo "To browse a specific folder, use:"
echo "  curl -H \"Authorization: Bearer \$TOKEN\" \\"
echo "    \"${API_BASE}/storage/browse?bucket=curatore-processed&prefix={org_id}/\""
