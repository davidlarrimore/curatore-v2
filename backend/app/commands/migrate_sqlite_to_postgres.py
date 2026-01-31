#!/usr/bin/env python3
# backend/app/commands/migrate_sqlite_to_postgres.py
"""
SQLite to PostgreSQL migration command for Curatore v2.

Migrates all data from SQLite database to PostgreSQL while preserving
all relationships and data integrity.

Usage:
    # Run from project root with both databases accessible
    python -m app.commands.migrate_sqlite_to_postgres

    # With custom SQLite path
    python -m app.commands.migrate_sqlite_to_postgres --sqlite-path ./data/curatore.db

    # Dry run (shows what would be migrated)
    python -m app.commands.migrate_sqlite_to_postgres --dry-run

Prerequisites:
    1. PostgreSQL container must be running: docker compose --profile postgres up -d postgres
    2. SQLite database must exist at ./data/curatore.db (or custom path)
    3. PostgreSQL should be empty or tables will be truncated

Example:
    # Start PostgreSQL first
    docker compose --profile postgres up -d postgres

    # Wait for it to be ready
    docker compose exec postgres pg_isready

    # Run migration
    docker exec curatore-backend python -m app.commands.migrate_sqlite_to_postgres
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text, MetaData, Table, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("curatore.migrate")


# Tables to migrate in order (respecting foreign key dependencies)
MIGRATION_ORDER = [
    "organizations",
    "users",
    "api_keys",
    "connections",
    "settings",
    "assets",
    "asset_versions",
    "extraction_results",
    "runs",
    "run_log_events",
    "scrape_collections",
    "scraped_pages",
    "sam_searches",
    "sam_solicitations",
    "sam_notices",
    "sharepoint_sync_configs",
    "sharepoint_synced_documents",
    "scheduled_tasks",
]


def get_sqlite_connection(sqlite_path: str):
    """Get SQLite connection (sync)."""
    # Handle both absolute and relative paths
    if sqlite_path.startswith("sqlite"):
        # Already a connection string
        conn_str = sqlite_path.replace("+aiosqlite", "")
    else:
        conn_str = f"sqlite:///{sqlite_path}"

    engine = create_engine(conn_str, echo=False)
    return engine


def get_postgres_url():
    """Get PostgreSQL connection URL from environment."""
    url = os.getenv("DATABASE_URL", "")
    if not url or "postgresql" not in url:
        # Build from components
        user = os.getenv("POSTGRES_USER", "curatore")
        password = os.getenv("POSTGRES_PASSWORD", "curatore_dev_password")
        host = os.getenv("POSTGRES_HOST", "postgres")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "curatore")
        url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    else:
        # Convert asyncpg to psycopg2 for sync operations
        url = url.replace("+asyncpg", "")
    return url


async def migrate_table(
    sqlite_engine,
    postgres_engine,
    table_name: str,
    dry_run: bool = False
) -> int:
    """Migrate a single table from SQLite to PostgreSQL."""
    logger.info(f"Migrating table: {table_name}")

    try:
        # Read all data from SQLite
        with sqlite_engine.connect() as sqlite_conn:
            # Check if table exists
            inspector = inspect(sqlite_engine)
            if table_name not in inspector.get_table_names():
                logger.warning(f"  Table {table_name} does not exist in SQLite, skipping")
                return 0

            result = sqlite_conn.execute(text(f"SELECT * FROM {table_name}"))
            columns = result.keys()
            rows = result.fetchall()

        if not rows:
            logger.info(f"  No data in {table_name}")
            return 0

        logger.info(f"  Found {len(rows)} rows to migrate")

        if dry_run:
            logger.info(f"  [DRY RUN] Would migrate {len(rows)} rows")
            return len(rows)

        # Insert into PostgreSQL
        with postgres_engine.connect() as pg_conn:
            # Check if table exists in PostgreSQL
            pg_inspector = inspect(postgres_engine)
            if table_name not in pg_inspector.get_table_names():
                logger.warning(f"  Table {table_name} does not exist in PostgreSQL, skipping")
                return 0

            # Clear existing data
            pg_conn.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
            pg_conn.commit()

            # Insert data in batches
            batch_size = 1000
            total_inserted = 0

            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]

                # Build insert statement
                col_names = ", ".join(columns)
                placeholders = ", ".join([f":{col}" for col in columns])

                insert_sql = text(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})")

                # Convert rows to dicts
                batch_dicts = [dict(zip(columns, row)) for row in batch]

                # Handle SQLite booleans (stored as 0/1) for PostgreSQL
                for row_dict in batch_dicts:
                    for key, value in row_dict.items():
                        # Convert SQLite integers to booleans for known boolean columns
                        if key in ('is_active', 'enabled', 'is_deleted', 'verified',
                                   'email_verified', 'is_admin', 'is_org_admin',
                                   'is_default', 'is_current', 'test_on_save',
                                   'auto_start', 'notify_on_failure', 'is_public'):
                            if value is not None:
                                row_dict[key] = bool(value)

                pg_conn.execute(insert_sql, batch_dicts)
                pg_conn.commit()
                total_inserted += len(batch)
                logger.info(f"  Inserted {total_inserted}/{len(rows)} rows")

            # Reset sequence for tables with auto-increment IDs (if applicable)
            # This is handled by PostgreSQL's SERIAL/BIGSERIAL types

            logger.info(f"  Successfully migrated {total_inserted} rows")
            return total_inserted

    except Exception as e:
        logger.error(f"  Error migrating {table_name}: {e}")
        raise


async def verify_migration(sqlite_engine, postgres_engine) -> bool:
    """Verify row counts match between SQLite and PostgreSQL."""
    logger.info("\n" + "=" * 60)
    logger.info("Verifying migration...")
    logger.info("=" * 60)

    all_match = True

    with sqlite_engine.connect() as sqlite_conn:
        with postgres_engine.connect() as pg_conn:
            for table_name in MIGRATION_ORDER:
                try:
                    # Get SQLite count
                    sqlite_inspector = inspect(sqlite_engine)
                    if table_name not in sqlite_inspector.get_table_names():
                        continue

                    sqlite_result = sqlite_conn.execute(
                        text(f"SELECT COUNT(*) FROM {table_name}")
                    )
                    sqlite_count = sqlite_result.scalar()

                    # Get PostgreSQL count
                    pg_inspector = inspect(postgres_engine)
                    if table_name not in pg_inspector.get_table_names():
                        logger.warning(f"  {table_name}: NOT IN POSTGRES")
                        all_match = False
                        continue

                    pg_result = pg_conn.execute(
                        text(f"SELECT COUNT(*) FROM {table_name}")
                    )
                    pg_count = pg_result.scalar()

                    if sqlite_count == pg_count:
                        logger.info(f"  ✓ {table_name}: {pg_count} rows")
                    else:
                        logger.error(f"  ✗ {table_name}: SQLite={sqlite_count}, PostgreSQL={pg_count}")
                        all_match = False

                except Exception as e:
                    logger.error(f"  ✗ {table_name}: Error - {e}")
                    all_match = False

    return all_match


async def run_migration(sqlite_path: str, dry_run: bool = False):
    """Run the full migration."""
    logger.info("=" * 60)
    logger.info("SQLite to PostgreSQL Migration")
    logger.info("=" * 60)
    logger.info(f"SQLite source: {sqlite_path}")
    logger.info(f"PostgreSQL target: {get_postgres_url().split('@')[1] if '@' in get_postgres_url() else get_postgres_url()}")
    logger.info(f"Dry run: {dry_run}")
    logger.info("=" * 60)

    # Verify SQLite file exists
    sqlite_file = sqlite_path
    if sqlite_path.startswith("sqlite"):
        sqlite_file = sqlite_path.split("///")[1].split("?")[0]

    if not os.path.exists(sqlite_file):
        logger.error(f"SQLite database not found: {sqlite_file}")
        logger.error("Please ensure the SQLite database exists before running migration.")
        return False

    # Connect to databases
    try:
        sqlite_engine = get_sqlite_connection(sqlite_path)
        logger.info("Connected to SQLite")
    except Exception as e:
        logger.error(f"Failed to connect to SQLite: {e}")
        return False

    try:
        postgres_engine = create_engine(get_postgres_url(), echo=False)
        # Test connection
        with postgres_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        logger.error("Ensure PostgreSQL is running: docker compose --profile postgres up -d postgres")
        return False

    # Run migrations
    total_rows = 0
    start_time = datetime.now()

    logger.info("\n" + "=" * 60)
    logger.info("Starting table migration...")
    logger.info("=" * 60)

    try:
        for table_name in MIGRATION_ORDER:
            rows = await migrate_table(sqlite_engine, postgres_engine, table_name, dry_run)
            total_rows += rows
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

    # Verify migration
    if not dry_run:
        success = await verify_migration(sqlite_engine, postgres_engine)
    else:
        success = True

    # Summary
    duration = (datetime.now() - start_time).total_seconds()
    logger.info("\n" + "=" * 60)
    logger.info("Migration Summary")
    logger.info("=" * 60)
    logger.info(f"Total rows migrated: {total_rows}")
    logger.info(f"Duration: {duration:.2f} seconds")
    logger.info(f"Status: {'SUCCESS' if success else 'FAILED'}")
    logger.info("=" * 60)

    if success and not dry_run:
        logger.info("\n✅ Migration complete!")
        logger.info("\nNext steps:")
        logger.info("  1. Update .env to use PostgreSQL: DATABASE_URL=postgresql+asyncpg://...")
        logger.info("  2. Restart services: docker compose down && docker compose --profile postgres up -d")
        logger.info("  3. Verify application works correctly")
        logger.info("  4. Optionally remove SQLite file: rm ./data/curatore.db")

    return success


def main():
    parser = argparse.ArgumentParser(
        description="Migrate SQLite database to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run migration with default paths
    python -m app.commands.migrate_sqlite_to_postgres

    # Dry run (show what would be migrated)
    python -m app.commands.migrate_sqlite_to_postgres --dry-run

    # Custom SQLite path
    python -m app.commands.migrate_sqlite_to_postgres --sqlite-path ./backup/curatore.db
        """
    )

    parser.add_argument(
        "--sqlite-path",
        default="./data/curatore.db",
        help="Path to SQLite database file (default: ./data/curatore.db)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes"
    )

    args = parser.parse_args()

    success = asyncio.run(run_migration(
        sqlite_path=args.sqlite_path,
        dry_run=args.dry_run
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
