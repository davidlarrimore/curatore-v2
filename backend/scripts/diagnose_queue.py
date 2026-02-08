#!/usr/bin/env python3
"""
Diagnostic script to check extraction queue state.

Run from backend directory:
    python scripts/diagnose_queue.py
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func, and_, text
from app.core.shared.database_service import database_service
from app.core.database.models import Asset, Run, ExtractionResult
from app.config import settings


async def diagnose():
    print("=" * 60)
    print("EXTRACTION QUEUE DIAGNOSTIC")
    print("=" * 60)

    # Check settings
    print("\n[1] SETTINGS")
    print(f"  extraction_queue_enabled: {settings.extraction_queue_enabled}")
    print(f"  database_url: {settings.database_url[:50]}...")

    # Queue configuration from config.yml
    from app.core.ops.queue_registry import queue_registry
    queue_registry._ensure_initialized()
    extraction_queue = queue_registry.get("extraction")
    print(f"\n[1b] QUEUE CONFIG (from config.yml)")
    print(f"  extraction.max_concurrent: {extraction_queue.max_concurrent if extraction_queue else 'N/A'}")
    print(f"  extraction.timeout_seconds: {extraction_queue.timeout_seconds if extraction_queue else 'N/A'}")

    async with database_service.get_session() as session:
        # Check Asset counts by status
        print("\n[2] ASSETS BY STATUS")
        result = await session.execute(
            select(Asset.status, func.count(Asset.id))
            .group_by(Asset.status)
        )
        for status, count in result.fetchall():
            print(f"  {status}: {count}")

        # Check Run counts by status (extraction type only)
        print("\n[3] EXTRACTION RUNS BY STATUS")
        result = await session.execute(
            select(Run.status, func.count(Run.id))
            .where(Run.run_type == "extraction")
            .group_by(Run.status)
        )
        rows = result.fetchall()
        if rows:
            for status, count in rows:
                print(f"  {status}: {count}")
        else:
            print("  (no extraction runs found)")

        # Check all Run types
        print("\n[4] ALL RUNS BY TYPE")
        result = await session.execute(
            select(Run.run_type, func.count(Run.id))
            .group_by(Run.run_type)
        )
        rows = result.fetchall()
        if rows:
            for run_type, count in rows:
                print(f"  {run_type}: {count}")
        else:
            print("  (no runs found)")

        # Find assets with pending status but no active extraction run
        print("\n[5] PENDING ASSETS WITHOUT ACTIVE EXTRACTION RUN")
        # Get pending assets
        pending_assets = await session.execute(
            select(Asset.id, Asset.original_filename, Asset.organization_id)
            .where(Asset.status == "pending")
            .limit(20)
        )
        pending_list = pending_assets.fetchall()

        orphaned_count = 0
        for asset_id, filename, org_id in pending_list:
            # Check if there's an active extraction run for this asset
            asset_id_str = str(asset_id)
            run_result = await session.execute(
                select(Run.id, Run.status, Run.run_type)
                .where(and_(
                    Run.run_type == "extraction",
                    Run.status.in_(["pending", "submitted", "running"]),
                ))
                .limit(100)
            )

            # Check if any run has this asset in input_asset_ids
            found = False
            for run_id, run_status, run_type in run_result.fetchall():
                run = await session.get(Run, run_id)
                if run and run.input_asset_ids and asset_id_str in [str(x) for x in run.input_asset_ids]:
                    found = True
                    break

            if not found:
                orphaned_count += 1
                if orphaned_count <= 5:
                    print(f"  Asset {asset_id} ({filename[:40]}...) - NO ACTIVE RUN")

        if orphaned_count > 5:
            print(f"  ... and {orphaned_count - 5} more orphaned assets")
        elif orphaned_count == 0:
            print("  (all pending assets have active extraction runs)")

        # Check recent extraction runs
        print("\n[6] RECENT EXTRACTION RUNS (last 10)")
        result = await session.execute(
            select(Run)
            .where(Run.run_type == "extraction")
            .order_by(Run.created_at.desc())
            .limit(10)
        )
        runs = result.scalars().all()
        if runs:
            for run in runs:
                asset_ids = run.input_asset_ids or []
                print(f"  Run {str(run.id)[:8]}... status={run.status}, "
                      f"assets={len(asset_ids)}, created={run.created_at}")
        else:
            print("  (no extraction runs found)")

        # Check ExtractionResult counts
        print("\n[7] EXTRACTION RESULTS BY STATUS")
        result = await session.execute(
            select(ExtractionResult.status, func.count(ExtractionResult.id))
            .group_by(ExtractionResult.status)
        )
        rows = result.fetchall()
        if rows:
            for status, count in rows:
                print(f"  {status}: {count}")
        else:
            print("  (no extraction results found)")

        # Check organizations
        print("\n[8] ASSETS BY ORGANIZATION")
        result = await session.execute(
            select(Asset.organization_id, func.count(Asset.id))
            .group_by(Asset.organization_id)
        )
        for org_id, count in result.fetchall():
            print(f"  {org_id}: {count} assets")

        print("\n[9] RUNS BY ORGANIZATION")
        result = await session.execute(
            select(Run.organization_id, func.count(Run.id))
            .where(Run.run_type == "extraction")
            .group_by(Run.organization_id)
        )
        rows = result.fetchall()
        if rows:
            for org_id, count in rows:
                print(f"  {org_id}: {count} extraction runs")
        else:
            print("  (no extraction runs found)")

    print("\n" + "=" * 60)
    print("DIAGNOSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(diagnose())
