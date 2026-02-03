# backend/app/database/__init__.py
"""
Database package for Curatore v2.

Provides SQLAlchemy models, base classes, and database session management.
"""

from .base import Base, get_db
from .models import (
    Organization,
    User,
    ApiKey,
    Connection,
    SystemSetting,
    AuditLog,
)
from .procedures import (
    Procedure,
    Pipeline,
    ProcedureTrigger,
    PipelineTrigger,
    PipelineRun,
    PipelineItemState,
    FunctionExecution,
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
    # Procedures framework
    "Procedure",
    "Pipeline",
    "ProcedureTrigger",
    "PipelineTrigger",
    "PipelineRun",
    "PipelineItemState",
    "FunctionExecution",
]
