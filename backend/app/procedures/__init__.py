# backend/app/procedures/__init__.py
"""
Curatore Procedures Framework

Procedures are schedulable, event-driven workflows that execute sequences
of functions. They can be:
- Triggered by cron schedules
- Triggered by events (e.g., sam_pull.completed)
- Triggered by webhooks
- Executed manually via API

Usage:
    from app.procedures import procedure_executor

    # Execute a procedure
    result = await procedure_executor.execute(
        session=session,
        procedure_slug="sam_daily_digest",
        organization_id=org_id,
        params={"naics_codes": ["541512"]},
    )
"""

from .base import BaseProcedure, ProcedureDefinition, StepDefinition
from .executor import ProcedureExecutor, procedure_executor
from .loader import ProcedureLoader, procedure_loader
from .discovery import ProcedureDiscoveryService, procedure_discovery_service

__all__ = [
    "BaseProcedure",
    "ProcedureDefinition",
    "StepDefinition",
    "ProcedureExecutor",
    "procedure_executor",
    "ProcedureLoader",
    "procedure_loader",
    "ProcedureDiscoveryService",
    "procedure_discovery_service",
]
