#!/usr/bin/env python3
"""
Pre-migration validation script for document_id columns.

This script checks all document_id values in the database to ensure they are
in valid UUID or legacy doc_* format before running the migration. This prevents
migration failures due to invalid data.

Usage:
    python scripts/validate_document_ids.py

Exit codes:
    0 - All document_id values are valid
    1 - Invalid document_id values found (migration will fail)
    2 - Database connection error

Tables checked:
    - artifacts.document_id
    - job_documents.document_id
    - job_logs.document_id
"""

import asyncio
import re
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import select, text
from app.services.database_service import database_service
from app.database.models import Artifact, JobDocument, JobLog
from app.utils.validators import is_valid_document_id


# Regex patterns
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)
LEGACY_PATTERN = re.compile(r'^doc_[0-9a-f]{12}$', re.IGNORECASE)


def validate_format(document_id: str) -> bool:
    """Check if document_id matches valid format."""
    if not document_id:
        return False
    return UUID_PATTERN.match(document_id) or LEGACY_PATTERN.match(document_id)


async def validate_artifacts_table():
    """Validate document_id values in artifacts table."""
    print("\nChecking artifacts table...")

    async with database_service.get_session() as session:
        # Get all distinct document_id values
        result = await session.execute(
            select(Artifact.document_id).distinct()
        )
        document_ids = [row[0] for row in result.fetchall()]

        if not document_ids:
            print("  ✓ No artifacts found (table empty)")
            return []

        print(f"  Found {len(document_ids)} distinct document_id values")

        invalid_ids = []
        for doc_id in document_ids:
            if not validate_format(doc_id):
                invalid_ids.append(("artifacts", doc_id))

        if invalid_ids:
            print(f"  ✗ {len(invalid_ids)} invalid document_id values found")
        else:
            print(f"  ✓ All document_id values are valid")

        return invalid_ids


async def validate_job_documents_table():
    """Validate document_id values in job_documents table."""
    print("\nChecking job_documents table...")

    async with database_service.get_session() as session:
        # Get all distinct document_id values
        result = await session.execute(
            select(JobDocument.document_id).distinct()
        )
        document_ids = [row[0] for row in result.fetchall()]

        if not document_ids:
            print("  ✓ No job documents found (table empty)")
            return []

        print(f"  Found {len(document_ids)} distinct document_id values")

        invalid_ids = []
        for doc_id in document_ids:
            if not validate_format(doc_id):
                invalid_ids.append(("job_documents", doc_id))

        if invalid_ids:
            print(f"  ✗ {len(invalid_ids)} invalid document_id values found")
        else:
            print(f"  ✓ All document_id values are valid")

        return invalid_ids


async def validate_job_logs_table():
    """Validate document_id values in job_logs table."""
    print("\nChecking job_logs table...")

    async with database_service.get_session() as session:
        # Get all distinct document_id values (excluding NULL)
        result = await session.execute(
            select(JobLog.document_id).distinct().where(JobLog.document_id.isnot(None))
        )
        document_ids = [row[0] for row in result.fetchall()]

        if not document_ids:
            print("  ✓ No job logs with document_id found (all NULL or table empty)")
            return []

        print(f"  Found {len(document_ids)} distinct document_id values")

        invalid_ids = []
        for doc_id in document_ids:
            if not validate_format(doc_id):
                invalid_ids.append(("job_logs", doc_id))

        if invalid_ids:
            print(f"  ✗ {len(invalid_ids)} invalid document_id values found")
        else:
            print(f"  ✓ All document_id values are valid")

        return invalid_ids


async def get_database_stats():
    """Get database statistics for context."""
    print("\nDatabase Statistics:")

    async with database_service.get_session() as session:
        # Count artifacts
        result = await session.execute(select(Artifact))
        artifact_count = len(result.fetchall())
        print(f"  - Artifacts: {artifact_count}")

        # Count job documents
        result = await session.execute(select(JobDocument))
        job_doc_count = len(result.fetchall())
        print(f"  - Job Documents: {job_doc_count}")

        # Count job logs
        result = await session.execute(select(JobLog))
        job_log_count = len(result.fetchall())
        print(f"  - Job Logs: {job_log_count}")

        total = artifact_count + job_doc_count + job_log_count
        print(f"  - Total rows to migrate: {total}")


async def main():
    """Main validation function."""
    print("=" * 70)
    print("Document ID Migration - Pre-Migration Validation")
    print("=" * 70)

    try:
        # Get database stats first
        await get_database_stats()

        # Validate each table
        all_invalid = []

        artifacts_invalid = await validate_artifacts_table()
        all_invalid.extend(artifacts_invalid)

        job_docs_invalid = await validate_job_documents_table()
        all_invalid.extend(job_docs_invalid)

        job_logs_invalid = await validate_job_logs_table()
        all_invalid.extend(job_logs_invalid)

        # Print summary
        print("\n" + "=" * 70)
        print("Validation Summary")
        print("=" * 70)

        if not all_invalid:
            print("\n✓ SUCCESS: All document_id values are valid!")
            print("\n  You can safely run the migration:")
            print("    cd backend")
            print("    alembic upgrade head")
            print("\n  Or rollback if needed:")
            print("    alembic downgrade -1")
            return 0

        else:
            print(f"\n✗ FAILURE: Found {len(all_invalid)} invalid document_id values")
            print("\nInvalid values (first 20):")

            for i, (table, doc_id) in enumerate(all_invalid[:20]):
                print(f"  {i+1}. {table}: {doc_id!r}")

            if len(all_invalid) > 20:
                print(f"  ... and {len(all_invalid) - 20} more")

            print("\n⚠ WARNING: Migration will fail with these invalid values!")
            print("\nTo fix:")
            print("  1. Manually update invalid document_id values to UUID format")
            print("  2. Or delete rows with invalid document_id values")
            print("  3. Re-run this validation script")
            print("\nExample SQL to update (PostgreSQL):")
            print("  UPDATE artifacts")
            print("  SET document_id = gen_random_uuid()::text")
            print("  WHERE document_id NOT ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'")
            print("    AND document_id NOT ~ '^doc_[0-9a-f]{12}$';")

            return 1

    except Exception as e:
        print(f"\n✗ ERROR: Database connection failed: {e}")
        print("\nPlease check:")
        print("  - Database is running")
        print("  - DATABASE_URL is correctly set in .env")
        print("  - Database contains the required tables")
        return 2


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
