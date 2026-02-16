#!/usr/bin/env python3
"""
Pre-start checks for Curatore v2.

Waits for dependencies (PostgreSQL, Redis, MinIO), runs Alembic migrations,
detects fresh installs, and auto-seeds baseline data.

Usage:
    # Full: wait + migrate + seed-if-fresh
    python -m app.core.commands.prestart

    # Only wait for dependencies
    python -m app.core.commands.prestart --wait-only

    # Wait + migrate, no auto-seed
    python -m app.core.commands.prestart --skip-seed

Exit codes:
    0: Success
    1: Dependency unavailable after retries
    2: Migration failure
    3: Seed failure
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import redis
import sqlalchemy
from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger("curatore.prestart")

# ============================================================================
# Configuration
# ============================================================================

PRESTART_DB_RETRIES = int(os.getenv("PRESTART_DB_RETRIES", "30"))
PRESTART_DB_RETRY_INTERVAL = float(os.getenv("PRESTART_DB_RETRY_INTERVAL", "2"))
PRESTART_REDIS_RETRIES = int(os.getenv("PRESTART_REDIS_RETRIES", "15"))
PRESTART_REDIS_RETRY_INTERVAL = float(os.getenv("PRESTART_REDIS_RETRY_INTERVAL", "2"))
PRESTART_MINIO_RETRIES = int(os.getenv("PRESTART_MINIO_RETRIES", "15"))
PRESTART_MINIO_RETRY_INTERVAL = float(os.getenv("PRESTART_MINIO_RETRY_INTERVAL", "2"))


# ============================================================================
# Dependency Waiting
# ============================================================================


def _get_sync_database_url() -> str:
    """Convert async DATABASE_URL to synchronous for pre-start checks."""
    url = os.getenv("DATABASE_URL", "postgresql+asyncpg://curatore:curatore_dev_password@postgres:5432/curatore")
    # Replace async driver with sync driver
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    url = url.replace("postgresql+aiosqlite://", "sqlite://")
    # If no explicit driver, assume psycopg2
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def wait_for_postgres() -> sqlalchemy.engine.Engine:
    """Wait for PostgreSQL to accept connections.

    Returns:
        The synchronous SQLAlchemy engine (for reuse in fresh-install detection).

    Raises:
        SystemExit(1): If PostgreSQL is unavailable after retries.
    """
    db_url = _get_sync_database_url()
    safe_url = db_url.split("@")[-1].split("?")[0] if "@" in db_url else db_url
    logger.info(f"Waiting for PostgreSQL ({safe_url})...")

    engine = create_engine(db_url, pool_pre_ping=True)

    for attempt in range(1, PRESTART_DB_RETRIES + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(f"   PostgreSQL ready (attempt {attempt}/{PRESTART_DB_RETRIES})")
            return engine
        except Exception as e:
            if attempt == PRESTART_DB_RETRIES:
                logger.error(f"   PostgreSQL unavailable after {PRESTART_DB_RETRIES} attempts: {e}")
                sys.exit(1)
            logger.info(f"   PostgreSQL not ready (attempt {attempt}/{PRESTART_DB_RETRIES}), retrying in {PRESTART_DB_RETRY_INTERVAL}s...")
            time.sleep(PRESTART_DB_RETRY_INTERVAL)

    # Unreachable, but satisfies type checker
    sys.exit(1)


def wait_for_redis() -> None:
    """Wait for Redis to accept connections.

    Raises:
        SystemExit(1): If Redis is unavailable after retries.
    """
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    logger.info("Waiting for Redis...")

    for attempt in range(1, PRESTART_REDIS_RETRIES + 1):
        try:
            r = redis.Redis.from_url(broker_url, socket_connect_timeout=5)
            r.ping()
            logger.info(f"   Redis ready (attempt {attempt}/{PRESTART_REDIS_RETRIES})")
            return
        except Exception as e:
            if attempt == PRESTART_REDIS_RETRIES:
                logger.error(f"   Redis unavailable after {PRESTART_REDIS_RETRIES} attempts: {e}")
                sys.exit(1)
            logger.info(f"   Redis not ready (attempt {attempt}/{PRESTART_REDIS_RETRIES}), retrying in {PRESTART_REDIS_RETRY_INTERVAL}s...")
            time.sleep(PRESTART_REDIS_RETRY_INTERVAL)


def wait_for_minio() -> None:
    """Wait for MinIO to accept connections.

    Skipped if USE_OBJECT_STORAGE is not true.

    Raises:
        SystemExit(1): If MinIO is unavailable after retries.
    """
    use_storage = os.getenv("USE_OBJECT_STORAGE", "true").lower() in {"1", "true", "yes"}
    if not use_storage:
        logger.info("   MinIO check skipped (USE_OBJECT_STORAGE is not true)")
        return

    endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
    secure = os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}
    scheme = "https" if secure else "http"
    health_url = f"{scheme}://{endpoint}/minio/health/live"
    logger.info(f"Waiting for MinIO ({endpoint})...")

    import urllib.request
    import urllib.error

    for attempt in range(1, PRESTART_MINIO_RETRIES + 1):
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info(f"   MinIO ready (attempt {attempt}/{PRESTART_MINIO_RETRIES})")
                    return
        except Exception as e:
            if attempt == PRESTART_MINIO_RETRIES:
                logger.error(f"   MinIO unavailable after {PRESTART_MINIO_RETRIES} attempts: {e}")
                sys.exit(1)
            logger.info(f"   MinIO not ready (attempt {attempt}/{PRESTART_MINIO_RETRIES}), retrying in {PRESTART_MINIO_RETRY_INTERVAL}s...")
            time.sleep(PRESTART_MINIO_RETRY_INTERVAL)


# ============================================================================
# Fresh Install Detection
# ============================================================================


def detect_fresh_install(engine: sqlalchemy.engine.Engine) -> bool:
    """Detect whether this is a fresh install (no Alembic version tracked).

    Args:
        engine: Synchronous SQLAlchemy engine (already connected).

    Returns:
        True if this is a fresh install.
    """
    insp = inspect(engine)
    has_table = insp.has_table("alembic_version")
    if not has_table:
        return True

    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM alembic_version")).scalar()
    return count == 0


# ============================================================================
# Migration Execution
# ============================================================================


def _create_all_tables(engine: sqlalchemy.engine.Engine) -> None:
    """Create all SQLAlchemy-defined tables and seed reference data (fresh install only).

    Uses Base.metadata.create_all() to create the base schema that
    Alembic migrations assume already exists, then inserts reference
    data that migrations would normally provide (e.g., roles).

    IMPORTANT — Reference data parity:
    When Alembic migrations insert reference data (e.g., roles), the same
    data must be seeded here for fresh installs (which skip migrations via
    stamp head). If you add a new migration that INSERTs reference data,
    you MUST also add the corresponding INSERT below.

    Current parity:
    - roles: 20260212_add_roles_table + 20260214_simplify_roles → admin, member
    """
    from app.core.database.base import Base
    from app.core.database import models  # noqa: F401 — register all models

    logger.info("   Creating base tables via SQLAlchemy...")
    Base.metadata.create_all(bind=engine)
    logger.info("   Base tables created")

    # Seed reference data that Alembic migrations normally insert
    logger.info("   Seeding reference data (roles)...")
    with engine.begin() as conn:
        # Insert roles (from 20260212_add_roles_table + 20260214_simplify_roles)
        conn.execute(text("""
            INSERT INTO roles (name, display_name, description, is_system_role,
                               can_manage_users, can_manage_org, can_manage_system,
                               created_at, updated_at)
            VALUES
                ('admin', 'System Admin',
                 'System-wide administrator with access to all organizations and system settings',
                 true, true, true, true, NOW(), NOW()),
                ('member', 'Member',
                 'Organization member with data access and CWR tool usage',
                 false, false, false, false, NOW(), NOW())
            ON CONFLICT (name) DO NOTHING
        """))
    logger.info("   Reference data seeded")


def _alembic_stamp_head() -> None:
    """Stamp Alembic version to head without running migrations.

    Used after create_all() on fresh installs so Alembic knows the
    schema is up to date.
    """
    backend_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
    result = subprocess.run(
        ["alembic", "stamp", "head"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Alembic stamp failed (exit code {result.returncode})")
        if result.stderr:
            logger.error(f"  stderr: {result.stderr.strip()}")
        sys.exit(2)
    logger.info("   Alembic stamped to head")


def run_migrations(*, is_fresh_install: bool = False, engine: Optional[sqlalchemy.engine.Engine] = None) -> None:
    """Handle database schema setup.

    On fresh install: create_all() + stamp head.
    On existing database: alembic upgrade head (idempotent).

    Args:
        is_fresh_install: Whether this is a brand-new database.
        engine: Synchronous engine (required for fresh installs).

    Raises:
        SystemExit(2): If migrations fail.
    """
    if is_fresh_install and engine is not None:
        logger.info("Running fresh install schema setup...")
        _create_all_tables(engine)
        _alembic_stamp_head()
        logger.info("   Fresh install schema complete")
        return

    logger.info("Running Alembic migrations...")

    # Determine the backend directory (where alembic.ini lives)
    backend_dir = str(Path(__file__).resolve().parent.parent.parent.parent)

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"Migration failed (exit code {result.returncode})")
        if result.stderr:
            logger.error(f"  stderr: {result.stderr.strip()}")
        if result.stdout:
            logger.info(f"  stdout: {result.stdout.strip()}")
        sys.exit(2)

    if result.stdout:
        for line in result.stdout.strip().splitlines():
            logger.info(f"   {line}")
    logger.info("   Migrations complete")


# ============================================================================
# Auto-Seed
# ============================================================================


async def _auto_seed() -> Dict[str, str]:
    """Seed baseline data for a fresh install.

    Creates system org, default org, enables data sources, and seeds
    scheduled tasks.  Admin user creation is excluded (stays manual).

    Returns:
        Dict with seed results.
    """
    from app.core.commands.seed import (
        create_default_organization,
        ensure_system_org,
        seed_data_source_overrides,
        seed_scheduled_tasks,
    )

    results: Dict[str, str] = {}

    try:
        await ensure_system_org()
        results["system_org"] = "ok"
    except Exception as e:
        logger.error(f"   Failed to create system org: {e}")
        logger.error("   System org is required — aborting startup")
        sys.exit(3)

    try:
        org = await create_default_organization()
        results["default_org"] = "ok"
    except Exception as e:
        logger.error(f"   Failed to create default org: {e}")
        results["default_org"] = f"error: {e}"
        org = None

    if org is not None:
        try:
            await seed_data_source_overrides(org)
            results["data_sources"] = "ok"
        except Exception as e:
            logger.warning(f"   Failed to enable data sources: {e}")
            results["data_sources"] = f"error: {e}"

    try:
        await seed_scheduled_tasks()
        results["scheduled_tasks"] = "ok"
    except Exception as e:
        logger.warning(f"   Failed to seed scheduled tasks: {e}")
        results["scheduled_tasks"] = f"error: {e}"

    return results


def auto_seed() -> Dict[str, str]:
    """Synchronous wrapper for _auto_seed()."""
    return asyncio.run(_auto_seed())


# ============================================================================
# Orchestrator
# ============================================================================


def run_prestart_sync(
    *,
    wait_only: bool = False,
    skip_seed: bool = False,
) -> Dict:
    """Run all pre-start checks synchronously.

    Args:
        wait_only: Only wait for dependencies; skip migrations and seeding.
        skip_seed: Wait and migrate, but skip auto-seed.

    Returns:
        Dict with results of each phase.
    """
    result: Dict = {
        "is_fresh_install": False,
        "migration_status": "skipped",
        "seed_status": "skipped",
    }

    # 1. Wait for dependencies
    engine = wait_for_postgres()
    wait_for_redis()
    wait_for_minio()

    if wait_only:
        engine.dispose()
        return result

    # 2. Detect fresh install
    is_fresh = detect_fresh_install(engine)
    result["is_fresh_install"] = is_fresh
    if is_fresh:
        logger.info("   Fresh install detected (no Alembic version)")
    else:
        logger.info("   Existing database detected")

    # 3. Run migrations (or create_all + stamp for fresh installs)
    run_migrations(is_fresh_install=is_fresh, engine=engine)
    result["migration_status"] = "ok"

    # Done with sync engine
    engine.dispose()

    # 4. Auto-seed if fresh install
    if is_fresh and not skip_seed:
        logger.info("   Seeding fresh install with baseline data...")
        seed_results = auto_seed()
        result["seed_status"] = "ok"
        result["seed_details"] = seed_results

        # Check for errors
        if any("error" in v for v in seed_results.values()):
            result["seed_status"] = "partial"
            logger.warning("   Some seed steps had errors (see details above)")

        logger.info("")
        logger.info("   To create an admin user, run:")
        logger.info("     python -m app.core.commands.seed --create-admin")
    elif is_fresh and skip_seed:
        logger.info("   Skipping auto-seed (--skip-seed)")

    return result


async def run_prestart(
    *,
    wait_only: bool = False,
    skip_seed: bool = False,
) -> Dict:
    """Run pre-start checks from within the async startup event.

    Runs synchronous dependency waiting in a thread pool to avoid
    blocking the event loop.

    Returns:
        Dict with results: {"is_fresh_install": bool, "migration_status": str, "seed_status": str}
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_prestart_sync(wait_only=wait_only, skip_seed=skip_seed),
    )


# ============================================================================
# CLI Entry Point
# ============================================================================


def main() -> None:
    """CLI entry point for pre-start checks."""
    parser = argparse.ArgumentParser(
        description="Curatore v2 pre-start: wait for dependencies, run migrations, seed if fresh",
    )
    parser.add_argument(
        "--wait-only",
        action="store_true",
        help="Only wait for dependencies (skip migrations and seeding)",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Wait and migrate, but skip auto-seed on fresh install",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    result = run_prestart_sync(
        wait_only=args.wait_only,
        skip_seed=args.skip_seed,
    )

    if result.get("is_fresh_install"):
        print("\n   Fresh install — database seeded with defaults")
        print("   Run `python -m app.core.commands.seed --create-admin` to create admin user")

    logger.info("Pre-start checks complete")


if __name__ == "__main__":
    main()
