"""
Central registry for scheduled task handlers.

Each handler is registered via the ``@register`` decorator, which captures
both the callable *and* the baseline task metadata (name, schedule, etc.).
This replaces the separate ``MAINTENANCE_HANDLERS`` dict in
``maintenance_handlers.py`` and the ``BASELINE_TASKS`` list in
``seed.py`` — both are now derived from a single source of truth.

Usage::

    from app.core.ops.scheduled_task_registry import register

    @register(
        task_type="health.report",
        name="system_health_report",
        display_name="System Health Report",
        description="Generate system health summary.",
        schedule_expression="0 6 * * *",
    )
    async def handle_health_report(session, run, config):
        ...

    # At runtime
    from app.core.ops.scheduled_task_registry import get_handler, get_baseline_tasks
    handler = get_handler("health.report")
    tasks = get_baseline_tasks()
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("curatore.ops.scheduled_task_registry")

# ---------------------------------------------------------------------------
# Registry data structures
# ---------------------------------------------------------------------------


@dataclass
class ScheduledHandlerEntry:
    """A registered handler together with its baseline scheduled-task metadata."""

    handler: Callable
    task_type: str
    name: str
    display_name: str
    description: str
    scope_type: str = "global"
    schedule_expression: str = "0 * * * *"
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    baseline: bool = True  # False = handler-only, not auto-seeded


_registry: Dict[str, ScheduledHandlerEntry] = {}
_discovered: bool = False


# ---------------------------------------------------------------------------
# @register decorator
# ---------------------------------------------------------------------------


def register(
    task_type: str,
    name: str = "",
    display_name: str = "",
    description: str = "",
    schedule_expression: str = "0 * * * *",
    scope_type: str = "global",
    enabled: bool = True,
    config: Optional[Dict[str, Any]] = None,
    baseline: bool = True,
):
    """Decorator that registers a handler and its baseline task metadata.

    Args:
        baseline: When False the handler is registered for dispatch but no
            scheduled-task row is auto-seeded (useful for dynamically-created
            tasks like ``procedure.execute``).
    """

    def decorator(fn: Callable) -> Callable:
        _registry[task_type] = ScheduledHandlerEntry(
            handler=fn,
            task_type=task_type,
            name=name,
            display_name=display_name,
            description=description,
            scope_type=scope_type,
            schedule_expression=schedule_expression,
            enabled=enabled,
            config=config or {},
            baseline=baseline,
        )
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_handler(task_type: str) -> Optional[Callable]:
    """Look up handler by *task_type*.  Replaces ``MAINTENANCE_HANDLERS.get()``."""
    entry = _registry.get(task_type)
    return entry.handler if entry else None


def get_baseline_tasks() -> List[Dict[str, Any]]:
    """Return baseline task definitions derived from all registered handlers.

    Each dict has the keys expected by ``ScheduledTaskService.create_task()``.
    """
    return [
        {
            "name": entry.name,
            "display_name": entry.display_name,
            "description": entry.description,
            "task_type": entry.task_type,
            "scope_type": entry.scope_type,
            "schedule_expression": entry.schedule_expression,
            "enabled": entry.enabled,
            "config": entry.config,
        }
        for entry in _registry.values()
        if entry.baseline
    ]


def discover_handlers() -> None:
    """Import handler modules so that ``@register`` decorators fire.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _discovered
    if _discovered:
        return
    # This import triggers all @register calls in maintenance_handlers.py
    import app.core.ops.maintenance_handlers  # noqa: F401

    _discovered = True
    logger.debug(
        "Discovered %d scheduled-task handlers: %s",
        len(_registry),
        ", ".join(_registry.keys()),
    )
