# backend/app/cwr/governance/__init__.py
"""
CWR Governance — Capability profiles and side-effect approval gates.

Modules:
    capability_profiles: Exposure-profile enforcement (which tools are available per context)
    approvals: Side-effect approval checks against organization policy
"""

from .capability_profiles import (
    check_exposure,
    get_available_tools,
    get_restricted_tools,
)
from .approvals import (
    ApprovalResult,
    SideEffectPolicy,
    check_side_effects,
    get_side_effect_functions,
)

__all__ = [
    # Capability profiles
    "check_exposure",
    "get_available_tools",
    "get_restricted_tools",
    # Approvals
    "ApprovalResult",
    "SideEffectPolicy",
    "check_side_effects",
    "get_side_effect_functions",
]
