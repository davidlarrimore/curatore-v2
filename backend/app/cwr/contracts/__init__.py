# backend/app/cwr/contracts/__init__.py
"""
CWR Contracts - Tool contracts and procedure validation.

Provides formal JSON Schema contracts for functions and validation
for procedure definitions.
"""

from .validation import validate_procedure, ValidationResult, ValidationError


def __getattr__(name):
    """Lazy imports to avoid circular import with tools package."""
    if name == "ToolContract":
        from .tool_contracts import ToolContract
        return ToolContract
    if name == "ContractGenerator":
        from .tool_contracts import ContractGenerator
        return ContractGenerator
    if name == "ToolContractPack":
        from .contract_pack import ToolContractPack
        return ToolContractPack
    if name == "get_tool_contract_pack":
        from .contract_pack import get_tool_contract_pack
        return get_tool_contract_pack
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ToolContract",
    "ContractGenerator",
    "ToolContractPack",
    "get_tool_contract_pack",
    "validate_procedure",
    "ValidationResult",
    "ValidationError",
]
