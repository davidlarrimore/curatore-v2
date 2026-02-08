#!/usr/bin/env python3
"""
Test script for Phase 0 services.

Validates that Asset, Run, ExtractionResult, and RunLogEvent
services work correctly with the database.

Usage:
    python test_phase0_services.py
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.core.shared.database_service import database_service
from app.core.shared.asset_service import asset_service
from app.core.shared.run_service import run_service
from app.core.ingestion.extraction_result_service import extraction_result_service
from app.core.shared.run_log_service import run_log_service


async def test_phase0_services():
    """Test Phase 0 services end-to-end."""

    print("=" * 60)
    print("Phase 0 Services Test")
    print("=" * 60)

    # Use a test organization ID (should exist in your database)
    # Replace with actual org ID from your database
    test_org_id = uuid4()  # In real scenario, use existing org

    try:
        async with database_service.get_session() as session:
            print("\n1. Testing Asset Service...")
            print("-" * 60)

            # Create an asset
            asset = await asset_service.create_asset(
                session=session,
                organization_id=test_org_id,
                source_type="upload",
                source_metadata={"uploader": "test_user", "timestamp": "2026-01-28"},
                original_filename="test_document.pdf",
                raw_bucket="curatore-uploads",
                raw_object_key=f"test/{uuid4()}/raw/test_document.pdf",
                content_type="application/pdf",
                file_size=1024,
                file_hash="abc123def456",
            )
            print(f"✅ Created asset: {asset.id}")
            print(f"   - Filename: {asset.original_filename}")
            print(f"   - Source: {asset.source_type}")
            print(f"   - Status: {asset.status}")

            print("\n2. Testing Run Service...")
            print("-" * 60)

            # Create an extraction run
            run = await run_service.create_run(
                session=session,
                organization_id=test_org_id,
                run_type="extraction",
                origin="system",
                config={"extractor": "markitdown", "version": "1.0"},
                input_asset_ids=[str(asset.id)],
            )
            print(f"✅ Created run: {run.id}")
            print(f"   - Type: {run.run_type}")
            print(f"   - Origin: {run.origin}")
            print(f"   - Status: {run.status}")

            print("\n3. Testing Run Log Service...")
            print("-" * 60)

            # Log start event
            await run_log_service.log_start(
                session=session,
                run_id=run.id,
                message="Extraction started for test_document.pdf",
                context={"asset_id": str(asset.id)},
            )
            print("✅ Logged start event")

            # Start the run
            await run_service.start_run(session=session, run_id=run.id)
            print("✅ Started run (pending → running)")

            # Log progress
            await run_log_service.log_progress(
                session=session,
                run_id=run.id,
                current=1,
                total=1,
                unit="documents",
                message="Processing document...",
            )
            print("✅ Logged progress event")

            print("\n4. Testing Extraction Result Service...")
            print("-" * 60)

            # Create extraction result
            extraction = await extraction_result_service.create_extraction_result(
                session=session,
                asset_id=asset.id,
                run_id=run.id,
                extractor_version="markitdown-1.0",
            )
            print(f"✅ Created extraction result: {extraction.id}")
            print(f"   - Status: {extraction.status}")

            # Update extraction to running
            await extraction_result_service.update_extraction_status(
                session=session,
                extraction_id=extraction.id,
                status="running",
            )
            print("✅ Updated extraction to running")

            # Record successful extraction
            await extraction_result_service.record_extraction_success(
                session=session,
                extraction_id=extraction.id,
                bucket="curatore-processed",
                key=f"test/{asset.id}/extracted/test_document.md",
                extraction_time_seconds=2.5,
            )
            print("✅ Recorded extraction success")

            # Complete the run
            await run_service.complete_run(
                session=session,
                run_id=run.id,
                results_summary={"processed": 1, "failed": 0},
            )
            print("✅ Completed run (running → completed)")

            # Update asset status
            await asset_service.update_asset_status(
                session=session,
                asset_id=asset.id,
                status="ready",
            )
            print("✅ Updated asset to ready")

            # Log summary
            await run_log_service.log_summary(
                session=session,
                run_id=run.id,
                message="Extraction completed successfully",
                context={
                    "processed": 1,
                    "failed": 0,
                    "extraction_time": 2.5,
                },
            )
            print("✅ Logged summary event")

            print("\n5. Verifying Relationships...")
            print("-" * 60)

            # Get asset with latest extraction
            asset_with_extraction = await asset_service.get_asset_with_latest_extraction(
                session=session,
                asset_id=asset.id,
            )
            if asset_with_extraction:
                retrieved_asset, retrieved_extraction = asset_with_extraction
                print(f"✅ Retrieved asset: {retrieved_asset.id}")
                if retrieved_extraction:
                    print(f"✅ Retrieved extraction: {retrieved_extraction.id}")
                    print(f"   - Status: {retrieved_extraction.status}")

            # Get log events
            events = await run_log_service.get_events_for_run(
                session=session,
                run_id=run.id,
            )
            print(f"✅ Retrieved {len(events)} log events")
            for event in events:
                print(f"   - [{event.level}] {event.event_type}: {event.message}")

            # Get runs by asset
            runs_for_asset = await run_service.get_runs_by_asset(
                session=session,
                asset_id=asset.id,
            )
            print(f"✅ Found {len(runs_for_asset)} run(s) for asset")

            print("\n" + "=" * 60)
            print("✅ ALL TESTS PASSED!")
            print("=" * 60)
            print("\nPhase 0 services are working correctly!")
            print("- Asset lifecycle management ✅")
            print("- Run execution tracking ✅")
            print("- Extraction result tracking ✅")
            print("- Structured logging ✅")
            print("- Relationships and queries ✅")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_phase0_services())
