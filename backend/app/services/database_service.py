# backend/app/services/database_service.py
"""
Database service for async SQLAlchemy session management.

Provides a singleton service for managing database connections,
sessions, and health checks. Supports both SQLite (development)
and PostgreSQL (production).

Usage:
    from app.services.database_service import database_service

    # Get async session (context manager)
    async with database_service.get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    # Initialize database (create tables)
    await database_service.init_db()

    # Health check
    health = await database_service.health_check()
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

from ..config import settings
from ..database.base import Base


class DatabaseService:
    """
    Database service for managing async SQLAlchemy sessions.

    Follows existing Curatore service patterns (singleton with global instance).
    Supports both SQLite (development) and PostgreSQL (production) with
    appropriate connection pooling and configuration.

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
        with appropriate settings for SQLite or PostgreSQL.
        """
        self._logger = logging.getLogger("curatore.database")
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker] = None
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """
        Initialize database engine based on DATABASE_URL.

        SQLite Configuration:
            - Uses aiosqlite async driver
            - check_same_thread=False for async support
            - Creates data directory if needed

        PostgreSQL Configuration:
            - Uses asyncpg async driver
            - Connection pooling: size=20, max_overflow=40
            - Pool pre-ping for connection health
            - Pool recycle every 3600 seconds
        """
        # Get database URL from environment
        database_url = os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./data/curatore.db"
        )

        self._logger.info(f"Initializing database: {database_url.split('@')[-1].split('?')[0]}")

        # SQLite configuration
        if database_url.startswith("sqlite"):
            # Create data directory if it doesn't exist
            if ":///" in database_url:
                db_path = database_url.split("///")[1].split("?")[0]
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                    self._logger.info(f"Created database directory: {db_dir}")

            connect_args = {"check_same_thread": False}
            self._engine = create_async_engine(
                database_url,
                connect_args=connect_args,
                pool_pre_ping=True,
                echo=settings.debug,
            )
            self._logger.info("Using SQLite database (development mode)")

        # PostgreSQL configuration
        else:
            pool_size = int(os.getenv("DB_POOL_SIZE", "20"))
            max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "40"))
            pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))

            self._engine = create_async_engine(
                database_url,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=True,
                pool_recycle=pool_recycle,
                echo=settings.debug,
            )
            self._logger.info(
                f"Using PostgreSQL database (pool_size={pool_size}, max_overflow={max_overflow})"
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
            from ..database import models  # noqa: F401

            await conn.run_sync(Base.metadata.create_all)

        self._logger.info("Database tables created successfully")

    async def health_check(self) -> Dict[str, Any]:
        """
        Check database connectivity and health.

        Executes a simple SELECT 1 query to verify database is accessible
        and responsive. Also gathers table statistics and database information.

        Returns:
            Dict with health status:
                {
                    "status": "healthy" | "unhealthy",
                    "connected": True | False,
                    "error": "error message" (if unhealthy),
                    "database_type": "sqlite" | "postgresql",
                    "tables": {"organizations": count, "users": count, ...},
                    "migration_version": "current_revision",
                    "database_size_mb": size (sqlite only)
                }

        Usage:
            health = await database_service.health_check()
            if health["status"] == "healthy":
                print("Database is healthy")
        """
        try:
            # Determine database type from URL
            database_url = os.getenv(
                "DATABASE_URL", "sqlite+aiosqlite:///./data/curatore.db"
            )
            db_type = "sqlite" if "sqlite" in database_url else "postgresql"

            async with self.get_session() as session:
                # Test connection
                await session.execute(text("SELECT 1"))

                # Get table counts
                from app.database.models import Organization, User, ApiKey, Connection, SystemSetting, AuditLog

                tables = {}
                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM organizations"))
                    tables["organizations"] = result.scalar() or 0
                except:
                    tables["organizations"] = 0

                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM users"))
                    tables["users"] = result.scalar() or 0
                except:
                    tables["users"] = 0

                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM api_keys"))
                    tables["api_keys"] = result.scalar() or 0
                except:
                    tables["api_keys"] = 0

                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM connections"))
                    tables["connections"] = result.scalar() or 0
                except:
                    tables["connections"] = 0

                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM system_settings"))
                    tables["system_settings"] = result.scalar() or 0
                except:
                    tables["system_settings"] = 0

                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM audit_logs"))
                    tables["audit_logs"] = result.scalar() or 0
                except:
                    tables["audit_logs"] = 0

                # Get migration version
                migration_version = "unknown"
                try:
                    result = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
                    version = result.scalar()
                    if version:
                        migration_version = version[:12]  # Show first 12 chars of revision
                except:
                    pass

            # Get database file size (SQLite only)
            database_size_mb = None
            if db_type == "sqlite":
                try:
                    if ":///" in database_url:
                        db_path = database_url.split("///")[1].split("?")[0]
                        if os.path.exists(db_path):
                            size_bytes = os.path.getsize(db_path)
                            database_size_mb = round(size_bytes / (1024 * 1024), 2)
                except:
                    pass

            result = {
                "status": "healthy",
                "connected": True,
                "database_type": db_type,
                "tables": tables,
                "migration_version": migration_version,
            }

            if database_size_mb is not None:
                result["database_size_mb"] = database_size_mb

            return result

        except Exception as e:
            self._logger.error(f"Database health check failed: {str(e)}")
            return {
                "status": "unhealthy",
                "connected": False,
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
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/curatore.db")
        db_type = "SQLite" if "sqlite" in db_url else "PostgreSQL"
        return f"<DatabaseService(type={db_type})>"


# Global singleton instance (following Curatore service pattern)
database_service = DatabaseService()
