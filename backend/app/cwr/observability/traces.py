# backend/app/cwr/observability/traces.py
"""
Trace Tree Reconstruction - Build execution trees from trace_id and parent_run_id.

Reconstructs the parent/child hierarchy of runs that share a trace_id,
useful for visualizing procedure execution flow.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Run

logger = logging.getLogger("curatore.cwr.observability.traces")


@dataclass
class TraceNode:
    """A node in the execution trace tree."""
    run_id: UUID
    run_type: str
    status: str
    started_at: Any = None
    completed_at: Any = None
    duration_ms: Optional[int] = None
    config: Dict[str, Any] = field(default_factory=dict)
    children: List["TraceNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "run_id": str(self.run_id),
            "run_type": self.run_type,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "config": self.config,
            "children": [c.to_dict() for c in self.children],
        }


async def get_trace_tree(
    session: AsyncSession,
    trace_id: UUID,
) -> Optional[TraceNode]:
    """
    Reconstruct the execution tree for a trace.

    Uses trace_id to find all related runs, then parent_run_id
    to build the tree hierarchy.

    Args:
        session: Database session
        trace_id: Trace identifier

    Returns:
        Root TraceNode with children, or None if no runs found
    """
    query = select(Run).where(Run.trace_id == trace_id).order_by(Run.created_at)
    result = await session.execute(query)
    runs = result.scalars().all()

    if not runs:
        return None

    # Build lookup maps
    nodes: Dict[UUID, TraceNode] = {}
    for run in runs:
        node = TraceNode(
            run_id=run.id,
            run_type=run.run_type,
            status=run.status,
            started_at=run.started_at,
            completed_at=run.completed_at,
            duration_ms=run.duration_ms,
            config=run.config or {},
        )
        nodes[run.id] = node

    # Build tree
    root = None
    for run in runs:
        node = nodes[run.id]
        if run.parent_run_id and run.parent_run_id in nodes:
            nodes[run.parent_run_id].children.append(node)
        else:
            if root is None:
                root = node

    return root
