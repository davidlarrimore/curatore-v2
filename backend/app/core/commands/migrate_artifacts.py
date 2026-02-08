"""
One-time migration to register missing upload artifacts for existing objects.

Scans the uploads bucket and creates Artifact records for objects that
do not already have an "uploaded" artifact entry.
"""
import argparse
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional, Tuple

from ..config import settings
from ..services.artifact_service import artifact_service
from ..services.database_service import database_service
from ..services.minio_service import get_minio_service

logger = logging.getLogger("curatore.migrate_artifacts")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register missing upload artifacts.")
    parser.add_argument(
        "--bucket",
        default=settings.minio_bucket_uploads,
        help="Bucket to scan (default: uploads bucket)",
    )
    parser.add_argument(
        "--default-org-id",
        default=None,
        help="Fallback organization UUID for keys without an org prefix",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without writing to the database",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="DB commit batch size",
    )
    return parser.parse_args()


def _parse_document_id(key: str, default_org_id: Optional[uuid.UUID]) -> Tuple[str, Optional[uuid.UUID]]:
    parts = key.split("/")
    if len(parts) >= 4 and parts[2] == "uploaded":
        try:
            org_id = uuid.UUID(parts[0])
        except ValueError:
            org_id = default_org_id
        return parts[1], org_id
    return key, default_org_id


async def _run_migration(args: argparse.Namespace) -> int:
    minio = get_minio_service()
    if not minio:
        raise RuntimeError("MinIO service unavailable")

    default_org_id = None
    if args.default_org_id:
        default_org_id = uuid.UUID(args.default_org_id)

    created = 0
    skipped = 0
    missing_org = 0
    processed = 0

    async with database_service.get_session() as session:
        for obj in minio.client.list_objects(args.bucket, recursive=True):
            if getattr(obj, "is_dir", False):
                continue

            key = obj.object_name
            document_id, org_id = _parse_document_id(key, default_org_id)
            processed += 1

            if not org_id:
                missing_org += 1
                logger.warning("Skipping %s: no organization id available", key)
                continue

            existing = await artifact_service.get_artifact_by_document(
                session=session,
                document_id=document_id,
                artifact_type="uploaded",
                organization_id=org_id,
            )
            if existing:
                skipped += 1
                continue

            if not args.dry_run:
                await artifact_service.create_artifact(
                    session=session,
                    organization_id=org_id,
                    document_id=document_id,
                    artifact_type="uploaded",
                    bucket=args.bucket,
                    object_key=key,
                    original_filename=Path(key).name,
                    content_type=None,
                    file_size=obj.size or None,
                    etag=obj.etag.strip('"') if obj.etag else None,
                    status="available",
                )
                created += 1

                if created % args.batch_size == 0:
                    await session.commit()
            else:
                created += 1

        if not args.dry_run:
            await session.commit()

    logger.info(
        "Migration complete: processed=%s created=%s skipped=%s missing_org=%s dry_run=%s",
        processed,
        created,
        skipped,
        missing_org,
        args.dry_run,
    )
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    asyncio.run(_run_migration(args))


if __name__ == "__main__":
    main()
