# backend/app/cwr/governance/capability_profiles.py
"""
Capability Profile Enforcement - Control which tools are available in each context.

Functions declare an `exposure_profile` (e.g., {"procedure": true, "agent": true})
that governs where they can be invoked.
"""

import logging
from typing import List

from app.cwr.tools.base import FunctionMeta
from app.cwr.tools.registry import function_registry, initialize_functions

logger = logging.getLogger("curatore.cwr.governance.profiles")


def check_exposure(meta: FunctionMeta, context_type: str) -> bool:
    """
    Check whether a function is allowed in the given context.

    Args:
        meta: Function metadata
        context_type: Context type ("procedure", "agent", "api", etc.)

    Returns:
        True if the function is exposed in this context
    """
    if not meta.exposure_profile:
        # No profile declared - default to allowed everywhere
        return True
    return meta.exposure_profile.get(context_type, False)


def get_available_tools(context_type: str) -> List[FunctionMeta]:
    """
    Get all functions available in the given context type.

    Args:
        context_type: Context type ("procedure", "agent", etc.)

    Returns:
        List of FunctionMeta for functions exposed in this context
    """
    initialize_functions()
    return [
        meta for meta in function_registry.list_all()
        if check_exposure(meta, context_type)
    ]


def get_restricted_tools(context_type: str) -> List[FunctionMeta]:
    """
    Get functions NOT available in the given context type.

    Useful for governance reporting and audit.

    Args:
        context_type: Context type ("procedure", "agent", etc.)

    Returns:
        List of FunctionMeta for functions NOT exposed in this context
    """
    initialize_functions()
    return [
        meta for meta in function_registry.list_all()
        if not check_exposure(meta, context_type)
    ]
