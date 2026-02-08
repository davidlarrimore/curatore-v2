#!/usr/bin/env python3
"""
Fix document IDs for files uploaded to custom folders.

This script finds artifacts where document_id is a file path (contains '/')
and updates them to use proper UUIDs.
"""

import sys
import uuid
from pathlib import Path

# Add backend to Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import asyncio
from sqlalchemy import select
from app.core.database.models import Artifact
from app.core.shared.database_service import database_service


async def fix_document_ids():
    """Fix document IDs that are file paths instead of UUIDs."""

    async with database_service.get_session() as session:
        # Find artifacts where document_id contains '/' (file path)
        result = await session.execute(
            select(Artifact).where(Artifact.document_id.contains('/'))
        )
        artifacts = result.scalars().all()

        if not artifacts:
            print("No artifacts found with invalid document IDs.")
            return

        print(f"Found {len(artifacts)} artifacts with invalid document IDs.")
        print()

        for artifact in artifacts:
            old_document_id = artifact.document_id
            new_document_id = str(uuid.uuid4())

            print(f"Artifact ID: {artifact.id}")
            print(f"  Object Key: {artifact.object_key}")
            print(f"  Old document_id: {old_document_id}")
            print(f"  New document_id: {new_document_id}")

            artifact.document_id = new_document_id
            print("  ✓ Updated")
            print()

        # Commit all changes
        await session.commit()
        print(f"Successfully updated {len(artifacts)} artifacts.")


if __name__ == "__main__":
    asyncio.run(fix_document_ids())
