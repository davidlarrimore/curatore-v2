#!/usr/bin/env python3
"""
Debug script to check job artifacts and help diagnose issues with job-specific file retrieval.

Usage:
    python scripts/debug_job_artifacts.py <job_id>
    python scripts/debug_job_artifacts.py <job_id> <document_id>
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.database_service import database_service
from app.services.artifact_service import artifact_service
from app.database.models import Job, JobDocument, Artifact
from sqlalchemy import select
import uuid


async def debug_job_artifacts(job_id_str: str, document_id: str = None):
    """Debug artifacts for a specific job and optionally a specific document."""

    try:
        job_id = uuid.UUID(job_id_str)
    except ValueError:
        print(f"❌ Invalid job_id format: {job_id_str}")
        return

    print(f"\n{'='*80}")
    print(f"Debugging Job: {job_id}")
    print(f"{'='*80}\n")

    async with database_service.get_session() as session:
        # Get job info
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            print(f"❌ Job not found: {job_id}")
            return

        print(f"📋 Job Info:")
        print(f"   Name: {job.name}")
        print(f"   Status: {job.status}")
        print(f"   Processed Folder: {job.processed_folder}")
        print(f"   Organization ID: {job.organization_id}")
        print(f"   Total Documents: {job.total_documents}")
        print(f"   Completed: {job.completed_documents}")
        print(f"   Failed: {job.failed_documents}")
        print()

        # Get job documents
        result = await session.execute(
            select(JobDocument).where(JobDocument.job_id == job_id)
        )
        job_documents = list(result.scalars().all())

        print(f"📄 Job Documents: {len(job_documents)}")
        print()

        for idx, job_doc in enumerate(job_documents, 1):
            print(f"   [{idx}] Document ID: {job_doc.document_id}")
            print(f"       Filename: {job_doc.filename}")
            print(f"       Status: {job_doc.status}")
            print(f"       Processed File Path: {job_doc.processed_file_path}")

            # Check if we should focus on this document
            if document_id and job_doc.document_id != document_id:
                print()
                continue

            # Look for artifacts for this document
            result = await session.execute(
                select(Artifact).where(
                    Artifact.document_id == job_doc.document_id,
                    Artifact.deleted_at.is_(None),
                )
            )
            artifacts = list(result.scalars().all())

            print(f"       Artifacts Found: {len(artifacts)}")

            for art_idx, artifact in enumerate(artifacts, 1):
                print(f"          [{art_idx}] Type: {artifact.artifact_type}")
                print(f"              Bucket: {artifact.bucket}")
                print(f"              Object Key: {artifact.object_key}")
                print(f"              Job ID: {artifact.job_id}")
                print(f"              Status: {artifact.status}")
                print(f"              Created: {artifact.created_at}")

                # Check if this artifact matches the job
                if artifact.job_id == job_id:
                    print(f"              ✅ Matches job {job_id}")
                elif artifact.job_id is None:
                    print(f"              ⚠️  No job_id set on artifact")
                else:
                    print(f"              ⚠️  Different job: {artifact.job_id}")

            print()

        # If specific document requested, do detailed check
        if document_id:
            print(f"\n{'='*80}")
            print(f"Detailed Check for Document: {document_id}")
            print(f"{'='*80}\n")

            # Try job-specific query
            print("🔍 Querying with job_id + document_id:")
            artifact = await artifact_service.get_artifact_by_document_and_job(
                session=session,
                document_id=document_id,
                job_id=job_id,
                artifact_type="processed",
            )
            if artifact:
                print(f"   ✅ Found: {artifact.object_key}")
            else:
                print(f"   ❌ Not found")

            # Try document-only query
            print("\n🔍 Querying with document_id only:")
            artifact = await artifact_service.get_artifact_by_document(
                session=session,
                document_id=document_id,
                artifact_type="processed",
            )
            if artifact:
                print(f"   ✅ Found: {artifact.object_key}")
                print(f"   Job ID on artifact: {artifact.job_id}")
            else:
                print(f"   ❌ Not found")

            # List all artifacts
            print("\n📦 All artifacts for this document:")
            result = await session.execute(
                select(Artifact).where(
                    Artifact.document_id == document_id,
                    Artifact.deleted_at.is_(None),
                )
            )
            all_artifacts = list(result.scalars().all())
            if all_artifacts:
                for artifact in all_artifacts:
                    print(f"   - Type: {artifact.artifact_type}, Job: {artifact.job_id}, Key: {artifact.object_key}")
            else:
                print("   (none)")

    print(f"\n{'='*80}")
    print("Debug complete!")
    print(f"{'='*80}\n")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_job_artifacts.py <job_id> [document_id]")
        sys.exit(1)

    job_id = sys.argv[1]
    document_id = sys.argv[2] if len(sys.argv) > 2 else None

    await debug_job_artifacts(job_id, document_id)


if __name__ == "__main__":
    asyncio.run(main())
