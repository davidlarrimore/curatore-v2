"""
Metrics API Router.

Provides endpoints for querying execution metrics from RunLogEvent data.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select

from app.core.database.models import Run, RunLogEvent, User
from app.core.shared.database_service import database_service
from app.dependencies import get_current_user

logger = logging.getLogger("curatore.api.metrics")

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get(
    "/procedures",
    summary="Get procedure execution metrics",
    description="Aggregate procedure execution metrics from RunLogEvent data for the last N days.",
)
async def get_procedure_metrics(
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    current_user: User = Depends(get_current_user),
):
    """Get procedure execution metrics for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    async with database_service.get_session() as session:
        # Query step_complete events with duration and function info
        step_events = await session.execute(
            select(
                RunLogEvent.context,
                RunLogEvent.level,
                RunLogEvent.created_at,
            )
            .join(Run, RunLogEvent.run_id == Run.id)
            .where(
                and_(
                    Run.organization_id == current_user.organization_id,
                    Run.run_type == "procedure",
                    RunLogEvent.event_type == "step_complete",
                    RunLogEvent.created_at >= cutoff,
                )
            )
        )
        step_rows = step_events.all()

        # Query procedure_complete events for overall stats
        proc_events = await session.execute(
            select(
                RunLogEvent.context,
                RunLogEvent.level,
            )
            .join(Run, RunLogEvent.run_id == Run.id)
            .where(
                and_(
                    Run.organization_id == current_user.organization_id,
                    Run.run_type == "procedure",
                    RunLogEvent.event_type == "procedure_complete",
                    RunLogEvent.created_at >= cutoff,
                )
            )
        )
        proc_rows = proc_events.all()

        # Aggregate procedure-level metrics
        total_runs = len(proc_rows)
        successful_runs = sum(
            1 for row in proc_rows
            if row.context and row.context.get("status") == "completed"
        )
        total_duration_ms = sum(
            row.context.get("duration_ms", 0)
            for row in proc_rows
            if row.context
        )

        # Aggregate function-level metrics
        by_function = {}
        for row in step_rows:
            ctx = row.context or {}
            func_name = ctx.get("function")
            if not func_name:
                continue

            if func_name not in by_function:
                by_function[func_name] = {
                    "calls": 0,
                    "total_ms": 0,
                    "errors": 0,
                }

            entry = by_function[func_name]
            entry["calls"] += 1
            entry["total_ms"] += ctx.get("duration_ms", 0)
            if ctx.get("status") in ("failed",):
                entry["errors"] += 1

        # Calculate averages
        for func_name, entry in by_function.items():
            entry["avg_ms"] = (
                round(entry["total_ms"] / entry["calls"])
                if entry["calls"] > 0
                else 0
            )
            del entry["total_ms"]  # Don't expose raw total

        return {
            "period_days": days,
            "total_runs": total_runs,
            "avg_duration_ms": (
                round(total_duration_ms / total_runs) if total_runs > 0 else 0
            ),
            "success_rate": (
                round(successful_runs / total_runs, 3) if total_runs > 0 else 0.0
            ),
            "by_function": by_function,
        }
