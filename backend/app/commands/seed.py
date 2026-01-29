#!/usr/bin/env python3
# backend/app/commands/seed.py
"""
Database seeding command for Curatore v2.

Creates initial organization and admin user from environment variables.
This is typically run once during initial setup to bootstrap the system.

Usage:
    # Create default organization and admin user
    python -m app.commands.seed --create-admin

    # Or run directly
    python backend/app/commands/seed.py --create-admin

Environment Variables Required:
    - ADMIN_EMAIL: Admin user email
    - ADMIN_USERNAME: Admin username
    - ADMIN_PASSWORD: Admin password
    - ADMIN_FULL_NAME: Admin full name (optional)
    - DEFAULT_ORG_NAME: Organization name
    - DEFAULT_ORG_SLUG: Organization slug (URL-friendly)

Example:
    export ADMIN_EMAIL=admin@example.com
    export ADMIN_USERNAME=admin
    export ADMIN_PASSWORD=SecurePass123!
    export DEFAULT_ORG_NAME="My Organization"
    python -m app.commands.seed --create-admin

Security:
    - Change default admin password immediately after first login
    - Store credentials securely (use secrets manager in production)
    - Never commit .env files with real credentials
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import settings
from app.database.models import Organization, User
from app.services.auth_service import auth_service
from app.services.database_service import database_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("curatore.seed")


async def create_default_organization() -> Organization:
    """
    Create the default organization from environment settings.

    Returns:
        Organization: Created organization

    Raises:
        Exception: If organization creation fails
    """
    logger.info("Creating default organization...")

    async with database_service.get_session() as session:
        # Check if organization already exists
        result = await session.execute(
            select(Organization).where(Organization.slug == settings.default_org_slug)
        )
        existing_org = result.scalar_one_or_none()

        if existing_org:
            logger.info(f"Organization already exists: {existing_org.name} (slug: {existing_org.slug})")
            return existing_org

        # Create new organization
        org = Organization(
            id=uuid4(),
            name=settings.default_org_name,
            display_name=settings.default_org_name,
            slug=settings.default_org_slug,
            is_active=True,
            settings={
                "quality_thresholds": {
                    "conversion": settings.default_conversion_threshold,
                    "clarity": settings.default_clarity_threshold,
                    "completeness": settings.default_completeness_threshold,
                    "relevance": settings.default_relevance_threshold,
                    "markdown": settings.default_markdown_threshold,
                },
                "auto_optimize": False,
            },
        )

        session.add(org)
        await session.commit()
        await session.refresh(org)

        logger.info(f"✅ Created organization: {org.name} (id: {org.id})")
        return org


async def create_admin_user(organization: Organization) -> User:
    """
    Create the initial admin user from environment settings.

    Args:
        organization: Organization to add admin to

    Returns:
        User: Created admin user

    Raises:
        Exception: If user creation fails
    """
    logger.info("Creating admin user...")

    async with database_service.get_session() as session:
        # Check if user already exists
        result = await session.execute(
            select(User).where(User.email == settings.admin_email)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            logger.info(f"Admin user already exists: {existing_user.email}")
            return existing_user

        # Check if username already exists
        result = await session.execute(
            select(User).where(User.username == settings.admin_username)
        )
        existing_username = result.scalar_one_or_none()

        if existing_username:
            logger.error(f"Username already taken: {settings.admin_username}")
            raise Exception(f"Username {settings.admin_username} is already taken")

        # Hash password
        logger.info("Hashing admin password...")
        password_hash = await auth_service.hash_password(settings.admin_password)

        # Create admin user
        admin = User(
            id=uuid4(),
            organization_id=organization.id,
            email=settings.admin_email,
            username=settings.admin_username,
            password_hash=password_hash,
            full_name=settings.admin_full_name,
            role="org_admin",  # Admin role
            is_active=True,
            is_verified=True,  # Pre-verified for admin
            settings={},
        )

        session.add(admin)
        await session.commit()
        await session.refresh(admin)

        logger.info(f"✅ Created admin user: {admin.email} (id: {admin.id})")
        logger.warning(
            f"⚠️  IMPORTANT: Change the default admin password immediately after first login!"
        )
        return admin


async def seed_scheduled_tasks() -> list:
    """
    Seed default scheduled maintenance tasks (Phase 5).

    Creates global scheduled tasks for system maintenance if they don't exist.

    Returns:
        list: List of created task names
    """
    from app.database.models import ScheduledTask

    logger.info("Seeding default scheduled tasks...")

    default_tasks = [
        {
            "name": "cleanup_expired_jobs",
            "display_name": "Cleanup Expired Jobs",
            "description": "Delete jobs that have exceeded their retention period based on organization settings.",
            "task_type": "gc.cleanup",
            "scope_type": "global",
            "schedule_expression": "0 3 * * *",  # Daily at 3 AM UTC
            "enabled": True,
            "config": {"dry_run": False},
        },
        {
            "name": "detect_orphaned_objects",
            "display_name": "Detect Orphaned Objects",
            "description": "Find orphaned objects: assets without extraction results, stuck runs, etc.",
            "task_type": "orphan.detect",
            "scope_type": "global",
            "schedule_expression": "0 4 * * 0",  # Weekly on Sunday at 4 AM UTC
            "enabled": True,
            "config": {},
        },
        {
            "name": "enforce_retention",
            "display_name": "Enforce Retention Policies",
            "description": "Enforce data retention policies by marking old artifacts as deleted.",
            "task_type": "retention.enforce",
            "scope_type": "global",
            "schedule_expression": "0 5 * * *",  # Daily at 5 AM UTC
            "enabled": True,
            "config": {"default_retention_days": 90, "dry_run": False},
        },
        {
            "name": "system_health_report",
            "display_name": "System Health Report",
            "description": "Generate a system health summary with asset, job, and extraction statistics.",
            "task_type": "health.report",
            "scope_type": "global",
            "schedule_expression": "0 6 * * *",  # Daily at 6 AM UTC
            "enabled": True,
            "config": {},
        },
    ]

    created_tasks = []

    async with database_service.get_session() as session:
        from app.services.scheduled_task_service import scheduled_task_service

        for task_data in default_tasks:
            # Check if task already exists
            existing = await scheduled_task_service.get_task_by_name(
                session, task_data["name"]
            )

            if existing:
                logger.info(f"  Scheduled task already exists: {task_data['name']}")
                continue

            # Create the task
            task = await scheduled_task_service.create_task(
                session=session,
                name=task_data["name"],
                display_name=task_data["display_name"],
                description=task_data["description"],
                task_type=task_data["task_type"],
                scope_type=task_data["scope_type"],
                schedule_expression=task_data["schedule_expression"],
                enabled=task_data["enabled"],
                config=task_data["config"],
            )

            created_tasks.append(task.name)
            logger.info(f"  ✅ Created scheduled task: {task.display_name}")

        await session.commit()

    return created_tasks


async def seed_database(create_admin: bool = True):
    """
    Seed the database with initial data.

    Args:
        create_admin: Whether to create admin user (default: True)
    """
    logger.info("=" * 80)
    logger.info("DATABASE SEEDING")
    logger.info("=" * 80)

    try:
        # Initialize database connection
        logger.info("Initializing database connection...")
        health = await database_service.health_check()
        if health.get("status") != "healthy":
            logger.error("Database is not healthy. Seeding aborted.")
            sys.exit(1)

        logger.info(f"Database connected: {health.get('database_type')}")
        logger.info("")

        # Create default organization
        org = await create_default_organization()
        logger.info("")

        # Create admin user if requested
        if create_admin:
            admin = await create_admin_user(org)
            logger.info("")

        # Seed default scheduled tasks (Phase 5)
        scheduled_tasks = await seed_scheduled_tasks()
        logger.info("")

        # Display summary
        if create_admin:
            logger.info("=" * 80)
            logger.info("SEEDING COMPLETE")
            logger.info("=" * 80)
            logger.info(f"Organization: {org.name}")
            logger.info(f"  - ID: {org.id}")
            logger.info(f"  - Slug: {org.slug}")
            logger.info("")
            logger.info(f"Admin User: {admin.email}")
            logger.info(f"  - ID: {admin.id}")
            logger.info(f"  - Username: {admin.username}")
            logger.info(f"  - Role: {admin.role}")
            logger.info("")
            logger.info(f"Scheduled Tasks: {len(scheduled_tasks)} created")
            for task_name in scheduled_tasks:
                logger.info(f"  - {task_name}")
            logger.info("")
            logger.info("You can now login with:")
            logger.info(f"  Email: {admin.email}")
            logger.info(f"  Password: {settings.admin_password}")
            logger.info("")
            logger.warning("⚠️  SECURITY WARNING:")
            logger.warning("  Change the default admin password immediately after first login!")
            logger.info("=" * 80)
        else:
            logger.info("=" * 80)
            logger.info("SEEDING COMPLETE (organization only)")
            logger.info("=" * 80)
            logger.info(f"Scheduled Tasks: {len(scheduled_tasks)} created")

    except Exception as e:
        logger.error(f"Seeding failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # Close database connection
        await database_service.close()


def main():
    """Main entry point for seed command."""
    parser = argparse.ArgumentParser(
        description="Seed Curatore v2 database with initial data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create organization and admin user
  python -m app.commands.seed --create-admin

  # Create only organization (no admin)
  python -m app.commands.seed

Environment Variables:
  ADMIN_EMAIL        Admin user email (default: admin@example.com)
  ADMIN_USERNAME     Admin username (default: admin)
  ADMIN_PASSWORD     Admin password (default: changeme)
  ADMIN_FULL_NAME    Admin full name (default: Admin User)
  DEFAULT_ORG_NAME   Organization name (default: Default Organization)
  DEFAULT_ORG_SLUG   Organization slug (default: default)

Security:
  - Change the default admin password immediately after first login
  - Use strong passwords in production
  - Store credentials in secrets manager (not .env files)
        """,
    )

    parser.add_argument(
        "--create-admin",
        action="store_true",
        help="Create admin user in addition to organization",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run seeding
    asyncio.run(seed_database(create_admin=args.create_admin))


if __name__ == "__main__":
    main()
