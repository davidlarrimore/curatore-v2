# backend/app/cwr/observability/runs.py
"""
CWR Run Queries - Query runs specific to procedures and pipelines.

Wraps the shared run_service with CWR-specific filters and projections.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Run

logger = logging.getLogger("curatore.cwr.observability.runs")


async def get_procedure_runs(
    session: AsyncSession,
    organization_id: UUID,
    slug: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get procedure execution runs.

    Args:
        session: Database session
        organization_id: Organization filter
        slug: Optional procedure slug filter
        status: Optional status filter
        limit: Page size
        offset: Page offset

    Returns:
        Dict with runs list and total count
    """
    query = select(Run).where(
        and_(
            Run.organization_id == organization_id,
            Run.run_type == "procedure",
        )
    )

    if slug:
        query = query.where(Run.config["procedure_slug"].astext == slug)
    if status:
        query = query.where(Run.status == status)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Fetch page
    query = query.order_by(desc(Run.created_at)).offset(offset).limit(limit)
    result = await session.execute(query)
    runs = result.scalars().all()

    return {
        "runs": runs,
        "total": total,
    }


async def get_pipeline_runs(
    session: AsyncSession,
    organization_id: UUID,
    slug: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get pipeline execution runs.

    Args:
        session: Database session
        organization_id: Organization filter
        slug: Optional pipeline slug filter
        status: Optional status filter
        limit: Page size
        offset: Page offset

    Returns:
        Dict with runs list and total count
    """
    query = select(Run).where(
        and_(
            Run.organization_id == organization_id,
            Run.run_type == "pipeline_run",
        )
    )

    if slug:
        query = query.where(Run.config["pipeline_slug"].astext == slug)
    if status:
        query = query.where(Run.status == status)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Fetch page
    query = query.order_by(desc(Run.created_at)).offset(offset).limit(limit)
    result = await session.execute(query)
    runs = result.scalars().all()

    return {
        "runs": runs,
        "total": total,
    }
