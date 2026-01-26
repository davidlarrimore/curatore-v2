#!/bin/bash

# Comprehensive diagnostic script for job folder issues

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
API_BASE="${BACKEND_URL}/api/v1"

if [ -z "$1" ]; then
    echo "Usage: ./scripts/diagnose_job_folder.sh <job_id>"
    echo ""
    echo "This script will check:"
    echo "  1. Job details (name, status, processed_folder)"
    echo "  2. Job documents (status, filenames)"
    echo "  3. Artifacts in database"
    echo "  4. Objects in MinIO storage"
    echo ""
    exit 1
fi

JOB_ID="$1"

echo "╔═══════════════════════════════════════════════════════════════════╗"
echo "║              Job Folder Diagnostic Report                         ║"
echo "╚═══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Job ID: $JOB_ID"
echo "Backend: $BACKEND_URL"
echo ""

# Check if we're inside the backend container or need to use docker
if command -v python3 &> /dev/null && [ -f "backend/app/main.py" ]; then
    PYTHON_CMD="python3"
    SCRIPT_DIR="scripts"
else
    PYTHON_CMD="docker exec -i curatore-backend python3"
    SCRIPT_DIR="/app/scripts"
fi

echo "════════════════════════════════════════════════════════════════════"
echo " Step 1: Check Job in Database"
echo "════════════════════════════════════════════════════════════════════"
echo ""

$PYTHON_CMD $SCRIPT_DIR/debug_job_artifacts.py "$JOB_ID"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " Step 2: Check MinIO Objects"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Get processed folder from job
PROCESSED_FOLDER=$($PYTHON_CMD -c "
import asyncio
import sys
sys.path.insert(0, '/app/backend')
from app.services.database_service import database_service
from app.database.models import Job
from sqlalchemy import select
import uuid

async def get_folder():
    async with database_service.get_session() as session:
        result = await session.execute(select(Job).where(Job.id == uuid.UUID('$JOB_ID')))
        job = result.scalar_one_or_none()
        if job:
            print(job.processed_folder or 'NONE', end='')
        else:
            print('NOT_FOUND', end='')

asyncio.run(get_folder())
" 2>/dev/null)

echo "Job processed_folder field: $PROCESSED_FOLDER"
echo ""

if [ "$PROCESSED_FOLDER" = "NOT_FOUND" ]; then
    echo "❌ Job not found in database!"
    exit 1
elif [ "$PROCESSED_FOLDER" = "NONE" ] || [ -z "$PROCESSED_FOLDER" ]; then
    echo "⚠️  No processed_folder set on job - this is the problem!"
    echo ""
    echo "The job doesn't have a processed_folder value, which means:"
    echo "  - The folder wasn't created when the job was created"
    echo "  - OR the job was created before the processed_folder feature"
    echo ""
    echo "To fix this, you need to either:"
    echo "  1. Re-run the job with the updated code, or"
    echo "  2. Manually set the processed_folder field in the database"
    echo ""
    exit 1
fi

echo "✅ Processed folder is set: $PROCESSED_FOLDER"
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo " Step 3: List Objects in Storage"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Use Python to list MinIO objects
$PYTHON_CMD -c "
import sys
sys.path.insert(0, '/app/backend')
from app.services.minio_service import get_minio_service

minio = get_minio_service()
if not minio:
    print('❌ MinIO service not available')
    sys.exit(1)

bucket = minio.bucket_processed
print(f'Listing objects in bucket: {bucket}')
print(f'Looking for prefix pattern: */{sys.argv[1]}/*')
print('')

count = 0
for obj in minio.client.list_objects(bucket, recursive=True):
    if '${PROCESSED_FOLDER}' in obj.object_name:
        count += 1
        size_kb = obj.size / 1024 if obj.size else 0
        print(f'  ✓ {obj.object_name} ({size_kb:.1f} KB)')

if count == 0:
    print('❌ No objects found with this folder name!')
    print('')
    print('This means:')
    print('  - Processing completed but files were not uploaded to storage')
    print('  - OR files were uploaded to a different folder')
    print('  - OR there was an error during file upload')
    print('')
    print('Check worker logs for upload errors:')
    print('  docker logs curatore-worker | grep -i \"failed to upload\"')
else:
    print('')
    print(f'✅ Found {count} objects in this job folder')
" "$PROCESSED_FOLDER"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " Step 4: Check Storage Browser API"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "Testing storage browse endpoint..."
echo ""

# Get the org_id from artifacts
ORG_ID=$($PYTHON_CMD -c "
import asyncio
import sys
sys.path.insert(0, '/app/backend')
from app.services.database_service import database_service
from app.database.models import Artifact
from sqlalchemy import select
import uuid

async def get_org():
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Artifact).where(Artifact.job_id == uuid.UUID('$JOB_ID')).limit(1)
        )
        artifact = result.scalar_one_or_none()
        if artifact:
            print(artifact.organization_id, end='')
        else:
            print('NONE', end='')

asyncio.run(get_org())
" 2>/dev/null)

if [ "$ORG_ID" != "NONE" ] && [ -n "$ORG_ID" ]; then
    echo "Organization ID: $ORG_ID"
    echo ""
    echo "To browse this in the storage UI, navigate to:"
    echo "  /storage"
    echo ""
    echo "Then browse to:"
    echo "  Bucket: curatore-processed"
    echo "  Folder: $ORG_ID/"
    echo ""
    echo "You should see the folder: $PROCESSED_FOLDER"
    echo ""
fi

echo "════════════════════════════════════════════════════════════════════"
echo " Diagnosis Complete"
echo "════════════════════════════════════════════════════════════════════"
echo ""
