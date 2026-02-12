# backend/app/functions/flow/__init__.py
"""
Flow control functions for the Curatore procedure engine.

These functions enable branching, routing, parallelism, and iteration
within procedures while maintaining the principle that every step calls
a function from the FunctionRegistry.

Functions:
    - if_branch: Conditional branching (if/else)
    - switch_branch: Multi-way routing based on value
    - parallel: Concurrent execution of independent branches
    - foreach: Iterate over a list with multi-step logic per item
"""

from .foreach import ForeachFunction
from .if_branch import IfBranchFunction
from .parallel import ParallelFunction
from .switch_branch import SwitchBranchFunction

__all__ = [
    "IfBranchFunction",
    "SwitchBranchFunction",
    "ParallelFunction",
    "ForeachFunction",
]
