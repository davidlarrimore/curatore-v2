# backend/app/cwr/contracts/__init__.py
"""
CWR Contracts - Tool contracts and procedure validation.

Provides ContractView for functions and validation for procedure definitions.
"""

from .validation import validate_procedure, ValidationResult, ValidationError


def __getattr__(name):
    """Lazy imports to avoid circular import with tools package."""
    if name == "ContractView":
        from ..tools.schema_utils import ContractView
        return ContractView
    if name == "ToolContractPack":
        from .contract_pack import ToolContractPack
        return ToolContractPack
    if name == "get_tool_contract_pack":
        from .contract_pack import get_tool_contract_pack
        return get_tool_contract_pack
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ContractView",
    "ToolContractPack",
    "get_tool_contract_pack",
    "validate_procedure",
    "ValidationResult",
    "ValidationError",
]
