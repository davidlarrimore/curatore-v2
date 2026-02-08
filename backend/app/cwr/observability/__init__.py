# backend/app/cwr/observability/__init__.py
"""
CWR Observability — Run queries, trace trees, and execution metrics.

Modules:
    runs: CWR-specific run queries (procedure and pipeline runs)
    traces: Trace tree reconstruction from trace_id / parent_run_id
    metrics: Aggregate execution statistics and function usage
"""

from .runs import (
    get_procedure_runs,
    get_pipeline_runs,
)
from .traces import (
    TraceNode,
    get_trace_tree,
)
from .metrics import (
    get_procedure_stats,
    get_function_usage,
)

__all__ = [
    # Runs
    "get_procedure_runs",
    "get_pipeline_runs",
    # Traces
    "TraceNode",
    "get_trace_tree",
    # Metrics
    "get_procedure_stats",
    "get_function_usage",
]
