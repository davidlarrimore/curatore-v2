# backend/app/cwr/observability/metrics.py
"""
CWR Execution Metrics - Aggregate metrics for procedures and functions.

Provides execution statistics like step durations, function call frequency,
and success rates.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Run

logger = logging.getLogger("curatore.cwr.observability.metrics")


async def get_procedure_stats(
    session: AsyncSession,
    organization_id: UUID,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Get procedure execution statistics.

    Args:
        session: Database session
        organization_id: Organization filter
        days: Number of days to look back

    Returns:
        Dict with execution statistics
    """
    since = datetime.utcnow() - timedelta(days=days)

    query = select(
        func.count(Run.id).label("total_runs"),
        func.count(Run.id).filter(Run.status == "completed").label("successful"),
        func.count(Run.id).filter(Run.status == "failed").label("failed"),
        func.avg(Run.duration_ms).label("avg_duration_ms"),
        func.max(Run.duration_ms).label("max_duration_ms"),
        func.min(Run.duration_ms).label("min_duration_ms"),
    ).where(
        and_(
            Run.organization_id == organization_id,
            Run.run_type == "procedure",
            Run.created_at >= since,
        )
    )

    result = await session.execute(query)
    row = result.one()

    total = row.total_runs or 0
    successful = row.successful or 0

    return {
        "total_runs": total,
        "successful": successful,
        "failed": row.failed or 0,
        "success_rate": round(successful / total * 100, 1) if total > 0 else 0,
        "avg_duration_ms": int(row.avg_duration_ms) if row.avg_duration_ms else None,
        "max_duration_ms": row.max_duration_ms,
        "min_duration_ms": row.min_duration_ms,
        "period_days": days,
    }


async def get_function_usage(
    session: AsyncSession,
    organization_id: UUID,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Get per-function call counts from procedure runs.

    Analyzes run results_summary to extract function invocation counts.
    Returns top functions by usage.

    Args:
        session: Database session
        organization_id: Organization filter
        days: Number of days to look back

    Returns:
        List of dicts with function name and call count
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Query completed procedure runs with results
    query = select(Run.results_summary).where(
        and_(
            Run.organization_id == organization_id,
            Run.run_type == "procedure",
            Run.created_at >= since,
            Run.results_summary.isnot(None),
        )
    )

    result = await session.execute(query)
    rows = result.scalars().all()

    # Aggregate function usage from step summary
    function_counts: Dict[str, int] = {}
    for summary in rows:
        if not isinstance(summary, dict):
            continue
        step_summary = summary.get("step_summary", {})
        for step_name, step_data in step_summary.items():
            if isinstance(step_data, dict):
                func_name = step_data.get("function")
                if func_name:
                    function_counts[func_name] = function_counts.get(func_name, 0) + 1

    # Sort by count descending
    sorted_funcs = sorted(function_counts.items(), key=lambda x: x[1], reverse=True)

    return [
        {"function": name, "call_count": count}
        for name, count in sorted_funcs
    ]
