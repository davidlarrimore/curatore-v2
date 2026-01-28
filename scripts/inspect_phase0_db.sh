#!/bin/bash
# Inspect Phase 0 database tables

DB_PATH="backend/data/curatore.db"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 0 Database Inspection${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ ! -f "$DB_PATH" ]; then
    echo -e "${RED}✗ Database not found at $DB_PATH${NC}"
    exit 1
fi

# Assets
echo -e "${YELLOW}1. Assets Table${NC}"
echo -e "${BLUE}---${NC}"
ASSET_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM assets;")
echo -e "Total assets: ${GREEN}${ASSET_COUNT}${NC}"
echo ""

if [ "$ASSET_COUNT" -gt 0 ]; then
    echo -e "Recent assets:"
    sqlite3 -header -column "$DB_PATH" "
    SELECT
        substr(id, 1, 8) || '...' as asset_id,
        source_type,
        original_filename,
        status,
        datetime(created_at) as created
    FROM assets
    ORDER BY created_at DESC
    LIMIT 5;
    "
    echo ""
fi

# Runs
echo -e "${YELLOW}2. Runs Table${NC}"
echo -e "${BLUE}---${NC}"
RUN_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM runs;")
echo -e "Total runs: ${GREEN}${RUN_COUNT}${NC}"
echo ""

if [ "$RUN_COUNT" -gt 0 ]; then
    echo -e "Recent runs:"
    sqlite3 -header -column "$DB_PATH" "
    SELECT
        substr(id, 1, 8) || '...' as run_id,
        run_type,
        origin,
        status,
        datetime(created_at) as created
    FROM runs
    ORDER BY created_at DESC
    LIMIT 5;
    "
    echo ""
fi

# Extraction Results
echo -e "${YELLOW}3. Extraction Results Table${NC}"
echo -e "${BLUE}---${NC}"
EXTRACTION_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM extraction_results;")
echo -e "Total extractions: ${GREEN}${EXTRACTION_COUNT}${NC}"
echo ""

if [ "$EXTRACTION_COUNT" -gt 0 ]; then
    echo -e "Recent extractions:"
    sqlite3 -header -column "$DB_PATH" "
    SELECT
        substr(id, 1, 8) || '...' as extraction_id,
        substr(asset_id, 1, 8) || '...' as asset_id,
        extractor_version,
        status,
        datetime(created_at) as created
    FROM extraction_results
    ORDER BY created_at DESC
    LIMIT 5;
    "
    echo ""
fi

# Run Log Events
echo -e "${YELLOW}4. Run Log Events Table${NC}"
echo -e "${BLUE}---${NC}"
LOG_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM run_log_events;")
echo -e "Total log events: ${GREEN}${LOG_COUNT}${NC}"
echo ""

if [ "$LOG_COUNT" -gt 0 ]; then
    echo -e "Recent log events:"
    sqlite3 -header -column "$DB_PATH" "
    SELECT
        level,
        event_type,
        message,
        datetime(created_at) as created
    FROM run_log_events
    ORDER BY created_at DESC
    LIMIT 10;
    "
    echo ""
fi

# Status Summary
echo -e "${YELLOW}5. Status Summary${NC}"
echo -e "${BLUE}---${NC}"

echo -e "Asset statuses:"
sqlite3 -header -column "$DB_PATH" "
SELECT status, COUNT(*) as count
FROM assets
GROUP BY status;
"
echo ""

echo -e "Run statuses:"
sqlite3 -header -column "$DB_PATH" "
SELECT status, COUNT(*) as count
FROM runs
GROUP BY status;
"
echo ""

echo -e "Extraction statuses:"
sqlite3 -header -column "$DB_PATH" "
SELECT status, COUNT(*) as count
FROM extraction_results
GROUP BY status;
"
echo ""

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Database Inspection Complete${NC}"
echo -e "${BLUE}========================================${NC}"
