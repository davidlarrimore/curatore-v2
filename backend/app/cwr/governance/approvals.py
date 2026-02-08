# backend/app/cwr/governance/approvals.py
"""
Side-Effect Approval Gate - Validate that side-effect functions are permitted.

Functions with `side_effects=True` (e.g., send_email, webhook, update_metadata)
modify external state. This module enforces organization-level policies on
whether these functions can execute.
"""

import logging
from enum import Enum
from typing import Dict, List, Optional

from app.cwr.tools.base import FunctionMeta

logger = logging.getLogger("curatore.cwr.governance.approvals")


class SideEffectPolicy(str, Enum):
    """Organization-level policy for side-effect functions."""
    ALLOW = "allow"        # Allow all side effects
    WARN = "warn"          # Log a warning but allow
    BLOCK = "block"        # Block side-effect functions


class ApprovalResult:
    """Result of a side-effect approval check."""

    def __init__(self, allowed: bool, policy: SideEffectPolicy, reason: str = ""):
        self.allowed = allowed
        self.policy = policy
        self.reason = reason

    def __bool__(self):
        return self.allowed


def check_side_effects(
    meta: FunctionMeta,
    step_name: str,
    policy: SideEffectPolicy = SideEffectPolicy.ALLOW,
) -> ApprovalResult:
    """
    Check whether a function's side effects are permitted under the given policy.

    Args:
        meta: Function metadata
        step_name: Name of the procedure step (for logging)
        policy: Organization-level side-effect policy

    Returns:
        ApprovalResult indicating whether the function can proceed
    """
    if not meta.side_effects:
        return ApprovalResult(True, policy, "Function has no side effects")

    if policy == SideEffectPolicy.ALLOW:
        return ApprovalResult(True, policy, "Side effects allowed by policy")

    if policy == SideEffectPolicy.WARN:
        logger.warning(
            f"Side-effect function '{meta.name}' executing in step '{step_name}' "
            f"(policy=warn)"
        )
        return ApprovalResult(True, policy, "Side effects allowed with warning")

    if policy == SideEffectPolicy.BLOCK:
        logger.error(
            f"Side-effect function '{meta.name}' blocked in step '{step_name}' "
            f"(policy=block)"
        )
        return ApprovalResult(
            False, policy,
            f"Function '{meta.name}' has side effects and is blocked by policy"
        )

    return ApprovalResult(True, policy)


def get_side_effect_functions() -> List[FunctionMeta]:
    """
    Get all registered functions that have side effects.

    Useful for governance auditing and policy configuration.

    Returns:
        List of FunctionMeta with side_effects=True
    """
    from app.cwr.tools.registry import function_registry, initialize_functions
    initialize_functions()
    return [meta for meta in function_registry.list_all() if meta.side_effects]
