# backend/app/services/database_service.py
"""
Database service for async SQLAlchemy session management with PostgreSQL.

Provides a singleton service for managing database connections,
sessions, and health checks. PostgreSQL is the required database backend.

Usage:
    from app.core.shared.database_service import database_service

    # Get async session (context manager)
    async with database_service.get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    # Initialize database (create tables)
    await database_service.init_db()

    # Health check
    health = await database_service.health_check()

PostgreSQL Configuration:
    Connection pooling is configured via environment variables:
    - DB_POOL_SIZE: Number of connections to maintain (default: 20)
    - DB_MAX_OVERFLOW: Extra connections allowed during peak load (default: 40)
    - DB_POOL_RECYCLE: Recycle connections after N seconds (default: 3600)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.database.base import Base


def _is_celery_worker() -> bool:
    """Check if we're running inside a Celery worker process."""
    # Celery sets these environment variables in worker processes
    return (
        os.getenv("CELERY_WORKER") == "1" or
        "celery" in os.getenv("_", "").lower() or
        os.getenv("FORKED_BY_MULTIPROCESSING") == "1"
    )


class DatabaseService:
    """
    Database service for managing async SQLAlchemy sessions with PostgreSQL.

    Follows existing Curatore service patterns (singleton with global instance).
    Optimized for PostgreSQL with connection pooling and health monitoring.

    Attributes:
        _engine: Async SQLAlchemy engine
        _session_factory: Async session factory
        _logger: Logger instance

    Methods:
        get_session(): Get async database session (context manager)
        init_db(): Initialize database (create all tables)
        health_check(): Check database connectivity
        close(): Close database engine and connections
    """

    def __init__(self):
        """
        Initialize database service.

        Reads DATABASE_URL from environment/config and creates async engine
        with PostgreSQL connection pooling.
        """
        self._logger = logging.getLogger("curatore.database")
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker] = None
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """
        Initialize PostgreSQL database engine.

        Configuration:
            - Uses asyncpg async driver for PostgreSQL
            - Connection pooling with configurable size
            - Pool pre-ping for connection health validation
            - Pool recycle to prevent stale connections

        Environment Variables:
            - DATABASE_URL: PostgreSQL connection string
            - DB_POOL_SIZE: Connection pool size (default: 20)
            - DB_MAX_OVERFLOW: Max overflow connections (default: 40)
            - DB_POOL_RECYCLE: Recycle time in seconds (default: 3600)

        Raises:
            ValueError: If DATABASE_URL is not a PostgreSQL URL
        """
        # Get database URL from environment
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://curatore:curatore_dev_password@postgres:5432/curatore"
        )

        # Validate PostgreSQL URL
        if "postgresql" not in database_url.lower():
            raise ValueError(
                f"PostgreSQL is required. Got: {database_url.split('@')[0]}...\n"
                "Set DATABASE_URL to a PostgreSQL connection string:\n"
                "  postgresql+asyncpg://user:password@host:5432/database"
            )

        # Log connection info (hide password)
        safe_url = database_url.split("@")[-1] if "@" in database_url else database_url
        self._logger.info(f"Initializing PostgreSQL database: {safe_url}")

        # Check if we're in a Celery worker - if so, use NullPool
        # to avoid asyncio event loop issues with pooled connections
        is_celery = _is_celery_worker()

        if is_celery:
            # Celery workers: Use NullPool to create fresh connections per task
            # This avoids "attached to a different loop" errors when asyncio.run()
            # creates a new event loop for each task
            self._engine = create_async_engine(
                database_url,
                poolclass=NullPool,  # No connection pooling - fresh connection each time
                echo=settings.debug,
                connect_args={
                    "server_settings": {
                        "application_name": "curatore-worker",
                        "jit": "off",
                    }
                },
            )
            self._logger.info("PostgreSQL configured with NullPool for Celery worker")
        else:
            # API/FastAPI: Use connection pooling for efficiency
            pool_size = int(os.getenv("DB_POOL_SIZE", "20"))
            max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "40"))
            pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))

            self._engine = create_async_engine(
                database_url,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=True,  # Validate connections before use
                pool_recycle=pool_recycle,  # Recycle connections periodically
                echo=settings.debug,  # SQL logging in debug mode
                connect_args={
                    "server_settings": {
                        "application_name": "curatore",
                        "jit": "off",  # Disable JIT for faster short queries
                    }
                },
            )
            self._logger.info(
                f"PostgreSQL connection pool: size={pool_size}, max_overflow={max_overflow}, recycle={pool_recycle}s"
            )

        # Create async session factory
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get async database session as context manager.

        Automatically handles commit on success and rollback on error.

        Usage:
            async with database_service.get_session() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                # Session automatically committed on exit

        Yields:
            AsyncSession: Async database session

        Raises:
            RuntimeError: If database is not initialized
            Exception: Any database errors (triggers rollback)
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def init_db(self) -> None:
        """
        Initialize database by creating all tables.

        Creates all tables defined in SQLAlchemy models if they don't exist.
        Safe to call multiple times (won't recreate existing tables).

        Usage:
            await database_service.init_db()

        Note:
            This is for initial setup only. For migrations, use Alembic.
        """
        if not self._engine:
            raise RuntimeError("Database engine not initialized")

        self._logger.info("Creating database tables...")

        async with self._engine.begin() as conn:
            # Import all models to ensure they're registered with Base
            from app.core.database import models  # noqa: F401

            await conn.run_sync(Base.metadata.create_all)

        self._logger.info("Database tables created successfully")

    async def health_check(self) -> Dict[str, Any]:
        """
        Check database connectivity and health.

        Executes queries to verify database is accessible and responsive.
        Gathers table statistics, connection pool status, and database info.

        Returns:
            Dict with health status:
                {
                    "status": "healthy" | "unhealthy",
                    "connected": True | False,
                    "error": "error message" (if unhealthy),
                    "database_type": "postgresql",
                    "tables": {"organizations": count, "users": count, ...},
                    "migration_version": "current_revision",
                    "pool_size": int,
                    "pool_checked_out": int,
                    "database_size_mb": float
                }

        Usage:
            health = await database_service.health_check()
            if health["status"] == "healthy":
                print("Database is healthy")
        """
        try:
            async with self.get_session() as session:
                # Test connection with a simple query
                await session.execute(text("SELECT 1"))

                # Get table counts
                tables = {}
                table_names = [
                    "organizations", "users", "api_keys", "connections",
                    "system_settings", "audit_logs", "assets", "runs"
                ]

                for table_name in table_names:
                    try:
                        result = await session.execute(
                            text(f"SELECT COUNT(*) FROM {table_name}")
                        )
                        tables[table_name] = result.scalar() or 0
                    except Exception:
                        tables[table_name] = 0

                # Get migration version
                migration_version = "unknown"
                try:
                    result = await session.execute(
                        text("SELECT version_num FROM alembic_version LIMIT 1")
                    )
                    version = result.scalar()
                    if version:
                        migration_version = version[:12]  # Show first 12 chars
                except Exception:
                    pass

                # Get database size
                database_size_mb = None
                try:
                    result = await session.execute(
                        text("SELECT pg_database_size(current_database())")
                    )
                    size_bytes = result.scalar()
                    if size_bytes:
                        database_size_mb = round(size_bytes / (1024 * 1024), 2)
                except Exception:
                    pass

            # Get pool statistics
            pool_size = None
            pool_checked_out = None
            if self._engine and hasattr(self._engine.pool, 'size'):
                pool_size = self._engine.pool.size()
                pool_checked_out = self._engine.pool.checkedout()

            result = {
                "status": "healthy",
                "connected": True,
                "database_type": "postgresql",
                "tables": tables,
                "migration_version": migration_version,
            }

            if pool_size is not None:
                result["pool_size"] = pool_size
                result["pool_checked_out"] = pool_checked_out

            if database_size_mb is not None:
                result["database_size_mb"] = database_size_mb

            return result

        except Exception as e:
            self._logger.error(f"Database health check failed: {str(e)}")
            return {
                "status": "unhealthy",
                "connected": False,
                "database_type": "postgresql",
                "error": str(e),
            }

    async def close(self) -> None:
        """
        Close database engine and all connections.

        Should be called on application shutdown to gracefully close
        all database connections.

        Usage:
            await database_service.close()
        """
        if self._engine:
            await self._engine.dispose()
            self._logger.info("Database connections closed")

    def __repr__(self) -> str:
        """String representation of DatabaseService."""
        return "<DatabaseService(type=PostgreSQL)>"


# Global singleton instance (following Curatore service pattern)
database_service = DatabaseService()
