# backend/app/cwr/procedures/__init__.py
"""
Curatore Procedures Framework

Procedures are schedulable, event-driven workflows that execute sequences
of functions. They can be:
- Triggered by cron schedules
- Triggered by events (e.g., sam_pull.completed)
- Triggered by webhooks
- Executed manually via API

Usage:
    from app.cwr.procedures import procedure_executor

    result = await procedure_executor.execute(
        session=session,
        procedure_slug="sam_daily_digest",
        organization_id=org_id,
        params={"naics_codes": ["541512"]},
    )
"""

from .runtime.executor import ProcedureExecutor, procedure_executor
from .store.definitions import BaseProcedure, ProcedureDefinition, StepDefinition
from .store.discovery import ProcedureDiscoveryService, procedure_discovery_service
from .store.loader import ProcedureLoader, procedure_loader

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
