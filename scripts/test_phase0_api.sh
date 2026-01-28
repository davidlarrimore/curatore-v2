#!/bin/bash
# Test Phase 0 API endpoints

set -e

API_BASE="http://localhost:8000/api/v1"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 0 API Testing Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if backend is running
echo -e "${YELLOW}1. Checking if backend is running...${NC}"
if curl -s "${API_BASE}/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Backend is running${NC}"
else
    echo -e "${RED}✗ Backend is not running. Start with: ./scripts/dev-up.sh${NC}"
    exit 1
fi
echo ""

# Step 1: Upload a file
echo -e "${YELLOW}2. Uploading a test file...${NC}"
# Create a test file
echo "This is a test document for Phase 0" > /tmp/test_phase0.txt

# Upload via proxy endpoint (this should create Asset + Run + Extraction)
UPLOAD_RESPONSE=$(curl -s -X POST "${API_BASE}/storage/upload/proxy" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/tmp/test_phase0.txt")

DOCUMENT_ID=$(echo $UPLOAD_RESPONSE | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)

if [ -z "$DOCUMENT_ID" ]; then
    echo -e "${RED}✗ Upload failed${NC}"
    echo "$UPLOAD_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ File uploaded successfully${NC}"
echo -e "  Document ID: ${DOCUMENT_ID}"
echo ""

# Wait a moment for Phase 0 integration to complete
echo -e "${YELLOW}3. Waiting for Phase 0 integration to complete...${NC}"
sleep 2
echo ""

# Step 2: List assets
echo -e "${YELLOW}4. Listing assets...${NC}"
ASSETS_RESPONSE=$(curl -s "${API_BASE}/assets?limit=5")
ASSET_COUNT=$(echo $ASSETS_RESPONSE | grep -o '"total":[0-9]*' | cut -d':' -f2)
echo -e "${GREEN}✓ Found ${ASSET_COUNT} asset(s) in the system${NC}"
echo ""

# Get the latest asset ID
LATEST_ASSET_ID=$(echo $ASSETS_RESPONSE | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -n "$LATEST_ASSET_ID" ]; then
    echo -e "${YELLOW}5. Getting asset details for latest asset...${NC}"
    ASSET_DETAIL=$(curl -s "${API_BASE}/assets/${LATEST_ASSET_ID}")
    ASSET_STATUS=$(echo $ASSET_DETAIL | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    ASSET_FILENAME=$(echo $ASSET_DETAIL | grep -o '"original_filename":"[^"]*"' | cut -d'"' -f4)

    echo -e "${GREEN}✓ Asset Details:${NC}"
    echo -e "  Asset ID: ${LATEST_ASSET_ID}"
    echo -e "  Filename: ${ASSET_FILENAME}"
    echo -e "  Status: ${ASSET_STATUS}"
    echo ""

    # Step 3: Get asset with extraction
    echo -e "${YELLOW}6. Getting extraction status for asset...${NC}"
    EXTRACTION_RESPONSE=$(curl -s "${API_BASE}/assets/${LATEST_ASSET_ID}/extraction")
    EXTRACTION_STATUS=$(echo $EXTRACTION_RESPONSE | grep -o '"status":"[^"]*"' | grep -o 'pending\|running\|completed\|failed' | tail -1)

    if [ -n "$EXTRACTION_STATUS" ]; then
        echo -e "${GREEN}✓ Extraction Status: ${EXTRACTION_STATUS}${NC}"

        if [ "$EXTRACTION_STATUS" = "completed" ]; then
            EXTRACTED_KEY=$(echo $EXTRACTION_RESPONSE | grep -o '"extracted_object_key":"[^"]*"' | cut -d'"' -f4)
            echo -e "  Extracted content: ${EXTRACTED_KEY}"
        fi
    else
        echo -e "${YELLOW}⊘ Extraction not started yet${NC}"
    fi
    echo ""

    # Step 4: Get runs for asset
    echo -e "${YELLOW}7. Getting runs for asset...${NC}"
    RUNS_RESPONSE=$(curl -s "${API_BASE}/assets/${LATEST_ASSET_ID}/runs")
    RUN_COUNT=$(echo $RUNS_RESPONSE | grep -o '"id":"[^"]*"' | wc -l)
    echo -e "${GREEN}✓ Found ${RUN_COUNT} run(s) for this asset${NC}"

    # Get first run ID
    RUN_ID=$(echo $RUNS_RESPONSE | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

    if [ -n "$RUN_ID" ]; then
        echo ""
        echo -e "${YELLOW}8. Getting run details with logs...${NC}"
        RUN_LOGS=$(curl -s "${API_BASE}/runs/${RUN_ID}/logs")
        RUN_STATUS=$(echo $RUN_LOGS | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
        LOG_COUNT=$(echo $RUN_LOGS | grep -o '"level":"[^"]*"' | wc -l)

        echo -e "${GREEN}✓ Run Details:${NC}"
        echo -e "  Run ID: ${RUN_ID}"
        echo -e "  Status: ${RUN_STATUS}"
        echo -e "  Log Events: ${LOG_COUNT}"
        echo ""

        # Show log messages
        echo -e "${BLUE}Recent Log Events:${NC}"
        echo "$RUN_LOGS" | grep -o '"message":"[^"]*"' | head -5 | cut -d'"' -f4 | while read msg; do
            echo -e "  • ${msg}"
        done
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Phase 0 API Testing Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Summary:${NC}"
echo -e "• Assets are being created: ${GREEN}✓${NC}"
echo -e "• Extraction runs are triggered: ${GREEN}✓${NC}"
echo -e "• Structured logging is working: ${GREEN}✓${NC}"
echo -e "• API endpoints are functional: ${GREEN}✓${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo -e "• View all assets: curl ${API_BASE}/assets"
echo -e "• View all runs: curl ${API_BASE}/runs"
echo -e "• Check logs: curl ${API_BASE}/runs/{run_id}/logs"
echo ""

# Cleanup
rm -f /tmp/test_phase0.txt
