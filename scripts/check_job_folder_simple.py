#!/usr/bin/env python3
"""
Simple job folder checker - run this from the project root or backend directory.

Usage:
    python3 scripts/check_job_folder_simple.py <job_id>
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.database_service import database_service
from app.services.minio_service import get_minio_service
from app.database.models import Job, Artifact
from sqlalchemy import select
import uuid


async def check_job_folder(job_id_str: str):
    """Check if job folder exists and has files."""

    try:
        job_id = uuid.UUID(job_id_str)
    except ValueError:
        print(f"❌ Invalid job_id format: {job_id_str}")
        return

    print("\n" + "="*70)
    print(f"Checking Job Folder: {job_id}")
    print("="*70 + "\n")

    async with database_service.get_session() as session:
        # Get job
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            print(f"❌ Job not found: {job_id}")
            return

        print(f"📋 Job: {job.name}")
        print(f"   Status: {job.status}")
        print(f"   Total Documents: {job.total_documents}")
        print(f"   Completed: {job.completed_documents}")
        print(f"   Failed: {job.failed_documents}")
        print()

        # Check processed_folder
        if not job.processed_folder:
            print("❌ PROBLEM: No processed_folder set on job!")
            print()
            print("   This is the root cause of your issue.")
            print()
            print("   Possible reasons:")
            print("   1. Job was created before the processed_folder feature")
            print("   2. Job creation failed to set processed_folder")
            print()
            print("   Solutions:")
            print("   1. Create a new job (will have processed_folder set)")
            print("   2. Re-process documents in a new job")
            print()
            return

        print(f"✅ Processed folder: {job.processed_folder}")
        print()

        # Check artifacts
        result = await session.execute(
            select(Artifact).where(
                Artifact.job_id == job_id,
                Artifact.artifact_type == "processed",
                Artifact.deleted_at.is_(None)
            )
        )
        artifacts = list(result.scalars().all())

        print(f"📦 Artifacts in database: {len(artifacts)}")
        if artifacts:
            for artifact in artifacts:
                print(f"   - {artifact.object_key}")
        else:
            print("   (none)")
        print()

    # Check MinIO
    minio = get_minio_service()
    if not minio:
        print("❌ MinIO service not available")
        return

    print(f"🗄️  Checking MinIO bucket: {minio.bucket_processed}")
    print(f"   Looking for folder: {job.processed_folder}")
    print()

    found_objects = []
    try:
        for obj in minio.client.list_objects(minio.bucket_processed, recursive=True):
            if job.processed_folder in obj.object_name:
                found_objects.append(obj)
                size_kb = obj.size / 1024 if obj.size else 0
                print(f"   ✓ {obj.object_name} ({size_kb:.1f} KB)")
    except Exception as e:
        print(f"❌ Error listing objects: {e}")
        return

    print()

    if not found_objects:
        print("❌ PROBLEM: No files found in MinIO with this folder name!")
        print()
        print("   This means the files were not uploaded to object storage.")
        print()
        print("   Check worker logs:")
        print("   docker logs curatore-worker | grep -i 'upload\\|error'")
        print()
        print("   Common causes:")
        print("   - Worker couldn't connect to MinIO")
        print("   - Processing completed but upload failed")
        print("   - Artifacts created but objects not uploaded")
        return

    print(f"✅ Found {len(found_objects)} objects in job folder")
    print()

    # Summary
    print("="*70)
    print("Summary:")
    print("="*70)
    print()

    if job.processed_folder and len(found_objects) > 0:
        print("✅ Job folder structure is correct!")
        print()
        print("   The folder should be visible in the storage browser at:")
        print(f"   Bucket: {minio.bucket_processed}")

        # Get org_id from first artifact
        if artifacts:
            org_id = str(artifacts[0].organization_id)
            print(f"   Path: {org_id}/ → {job.processed_folder}/")
        else:
            print(f"   Path: <org_id>/ → {job.processed_folder}/")

        print()
        print("   If you don't see it:")
        print("   1. Try refreshing the storage browser page")
        print("   2. Make sure you're browsing the curatore-processed bucket")
        print("   3. Navigate into your organization folder first")
    else:
        print("❌ Job folder has issues - see details above")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/check_job_folder_simple.py <job_id>")
        sys.exit(1)

    job_id = sys.argv[1]
    asyncio.run(check_job_folder(job_id))
