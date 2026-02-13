# backend/app/database/__init__.py
"""
Database package for Curatore v2.

Provides SQLAlchemy models, base classes, and database session management.
"""

from .base import Base, get_db
from .models import (
    ApiKey,
    AuditLog,
    CollectionChunk,
    CollectionVectorSync,
    Connection,
    Organization,
    SearchCollection,
    SystemSetting,
    User,
)
from .procedures import (
    FunctionExecution,
    Pipeline,
    PipelineItemState,
    PipelineRun,
    PipelineTrigger,
    Procedure,
    ProcedureTrigger,
)

__all__ = [
    "Base",
    "get_db",
    "Organization",
    "User",
    "ApiKey",
    "Connection",
    "SystemSetting",
    "AuditLog",
    # Search collections
    "SearchCollection",
    "CollectionVectorSync",
    "CollectionChunk",
    # Procedures framework
    "Procedure",
    "Pipeline",
    "ProcedureTrigger",
    "PipelineTrigger",
    "PipelineRun",
    "PipelineItemState",
    "FunctionExecution",
]
