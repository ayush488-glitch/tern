"""M5 — the unified tool surface.

ADR-0003 says: one Tool Protocol; native, browser, and MCP are sibling
implementations. S9 ships native only; browser and MCP land in S13 against
the same contract.

The agent core (M3) and the loop (M1) only ever import from this package.
They never know which family a tool came from. That's the whole point of
the unification — adding a third sibling later is a new file, not a refactor.
"""

from __future__ import annotations

from tern.tools.permissions import (
    ApprovalDecision,
    Mode,
    PermissionGate,
    ToolBlocked,
)
from tern.tools.protocol import (
    Tool,
    ToolAnnotations,
    ToolContext,
    ToolResult,
    spec_for,
)
from tern.tools.registry import Registry

__all__ = [
    "ApprovalDecision",
    "Mode",
    "PermissionGate",
    "Registry",
    "Tool",
    "ToolAnnotations",
    "ToolBlocked",
    "ToolContext",
    "ToolResult",
    "spec_for",
]
