# backend/app/database/base.py
"""
SQLAlchemy base class and session management.

Provides the declarative base for all models and async session factory.
"""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator

# Declarative base for all models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function for FastAPI to get async database session.

    Usage in FastAPI routes:
        @router.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            # Use db session here
            pass

    Yields:
        AsyncSession: Async database session
    """
    from ..services.database_service import database_service

    async with database_service.get_session() as session:
        yield session
