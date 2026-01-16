#!/usr/bin/env python3
"""
Script to fix filenames in existing jobs by looking up original filenames from the filesystem.
Run this inside the backend container: python -m scripts.fix_job_filenames [job_id]
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database_service import database_service
from app.services.job_service import _get_original_filename
from app.database.models import Job, JobDocument
from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def fix_job_filenames(job_id: str = None):
    """Fix filenames for a specific job or all jobs."""
    # Database service initializes automatically on first use

    async with database_service.get_session() as session:
        # Build query with eager loading of job relationship
        if job_id:
            query = select(JobDocument).options(selectinload(JobDocument.job)).join(Job).where(Job.id == job_id)
        else:
            query = select(JobDocument).options(selectinload(JobDocument.job))

        result = await session.execute(query)
        job_documents = result.scalars().all()

        print(f"Found {len(job_documents)} job documents to check")

        updated_count = 0
        for job_doc in job_documents:
            # Check if filename looks like a hash (32 hex chars)
            if len(job_doc.filename) == 32 and all(c in '0123456789abcdef' for c in job_doc.filename.lower()):
                # Try to find the original filename
                original_filename = _get_original_filename(job_doc.document_id, job_doc.job.organization_id)

                if original_filename != job_doc.document_id:
                    print(f"Updating {job_doc.document_id[:8]}...")
                    print(f"  Old: {job_doc.filename}")
                    print(f"  New: {original_filename}")
                    job_doc.filename = original_filename
                    updated_count += 1
                else:
                    print(f"Could not find original filename for {job_doc.document_id[:8]}")

        if updated_count > 0:
            await session.commit()
            print(f"\nUpdated {updated_count} filenames")
        else:
            print("\nNo updates needed")


if __name__ == "__main__":
    job_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(fix_job_filenames(job_id))
