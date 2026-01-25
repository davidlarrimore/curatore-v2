#!/usr/bin/env bash
# ============================================================================
# Verification Script: Object Storage Migration
# ============================================================================
# This script verifies that the filesystem-to-object-storage migration
# was completed successfully.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "🔍 Verifying object storage migration..."
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
WARNINGS=0

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

echo "=== Phase 1: Deleted Services ==="
for service in path_service deduplication_service retention_service metadata_service; do
    if [ ! -f "backend/app/services/${service}.py" ]; then
        check_pass "Deleted ${service}.py"
    else
        check_fail "${service}.py still exists"
    fi
done
echo ""

echo "=== Phase 2: Deleted Test Files ==="
for test in test_path_service test_deduplication_service test_retention_service test_metadata_service test_hierarchical_storage_integration; do
    if [ ! -f "backend/tests/${test}.py" ]; then
        check_pass "Deleted ${test}.py"
    else
        check_fail "${test}.py still exists"
    fi
done
echo ""

echo "=== Phase 3: Configuration Files ==="
if grep -q "USE_OBJECT_STORAGE=true" .env.example 2>/dev/null; then
    check_pass "USE_OBJECT_STORAGE=true in .env.example"
else
    check_fail "USE_OBJECT_STORAGE not set to true in .env.example"
fi

if ! grep -q "FILES_ROOT\|UPLOAD_DIR\|PROCESSED_DIR\|BATCH_DIR" .env.example 2>/dev/null; then
    check_pass "Filesystem vars removed from .env.example"
else
    check_warn "Filesystem vars still in .env.example"
fi

if ! grep -q "./files:/app/files" docker-compose.yml 2>/dev/null; then
    check_pass "Filesystem volume mounts removed from docker-compose.yml"
else
    check_fail "Filesystem volume mounts still in docker-compose.yml"
fi

if ! grep -q "profiles:" docker-compose.yml | grep -A2 "minio" 2>/dev/null; then
    check_pass "MinIO profile removed (starts by default)"
else
    check_warn "MinIO still has profile in docker-compose.yml"
fi
echo ""

echo "=== Phase 4: Storage Initialization ==="
if [ -f "backend/app/commands/init_storage.py" ]; then
    check_pass "Created init_storage.py command"
else
    check_fail "Missing init_storage.py command"
fi

if [ -f "scripts/init_storage.sh" ]; then
    check_pass "Created init_storage.sh script"
else
    check_fail "Missing init_storage.sh script"
fi
echo ""

echo "=== Phase 5: Service Refactoring ==="
if ! grep -q "save_uploaded_file\|list_uploaded_files\|clear_runtime_files" backend/app/services/document_service.py 2>/dev/null; then
    check_pass "Filesystem methods removed from document_service.py"
else
    check_warn "Some filesystem methods still in document_service.py"
fi

if grep -q "_download_processed_file" backend/app/services/zip_service.py 2>/dev/null; then
    check_pass "ZIP service uses _download_processed_file()"
else
    check_fail "ZIP service missing _download_processed_file()"
fi
echo ""

echo "=== Phase 6: Task Changes ==="
if grep -q "artifact_id is required" backend/app/tasks.py 2>/dev/null; then
    check_pass "Tasks enforce artifact_id requirement"
else
    check_fail "Tasks don't enforce artifact_id"
fi

if ! grep -q "def cleanup_expired_files_task" backend/app/tasks.py 2>/dev/null; then
    check_pass "Removed cleanup_expired_files_task"
else
    check_fail "cleanup_expired_files_task still exists"
fi
echo ""

echo "=== Phase 7: API Endpoints ==="
if grep -q "deprecated=True" backend/app/api/v1/routers/documents.py 2>/dev/null; then
    check_pass "Upload endpoint marked as deprecated"
else
    check_warn "Upload endpoint not marked deprecated"
fi

if grep -q "minio.delete_all_objects_in_bucket" backend/app/api/v1/routers/system.py 2>/dev/null; then
    check_pass "System reset uses MinIO deletion"
else
    check_fail "System reset doesn't use MinIO deletion"
fi
echo ""

echo "=== Phase 8: Import Validation ==="
if ! grep -q "from.*path_service import\|from.*deduplication_service import\|from.*retention_service import\|from.*metadata_service import" backend/app/services/job_service.py 2>/dev/null; then
    check_pass "No deleted service imports in job_service.py"
else
    check_fail "Deleted service imports found in job_service.py"
fi
echo ""

echo "=== Phase 9: New Test Files ==="
if [ -f "backend/tests/test_object_storage_integration.py" ]; then
    check_pass "Created test_object_storage_integration.py"
else
    check_fail "Missing test_object_storage_integration.py"
fi

if [ -f "backend/tests/test_task_object_storage.py" ]; then
    check_pass "Created test_task_object_storage.py"
else
    check_fail "Missing test_task_object_storage.py"
fi
echo ""

echo "=== Phase 10: Documentation ==="
if grep -q "Object Storage (S3/MinIO) - REQUIRED" CLAUDE.md 2>/dev/null; then
    check_pass "Documentation updated to state object storage is required"
else
    check_fail "Documentation not updated"
fi
echo ""

echo "============================================"
echo "Results:"
echo -e "${GREEN}Passed: $PASSED${NC}"
if [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
fi
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $FAILED${NC}"
    echo ""
    echo "⚠️  Migration verification found issues. Please review failed checks."
    exit 1
else
    echo ""
    echo "✅ Migration verification completed successfully!"
    echo ""
    echo "Next steps:"
    echo "  1. Start services: ./scripts/dev-up.sh"
    echo "  2. Verify MinIO is running: curl http://localhost:9000/minio/health/live"
    echo "  3. Run backend tests: pytest backend/tests -v"
    echo "  4. Test upload workflow via frontend or API"
    exit 0
fi
