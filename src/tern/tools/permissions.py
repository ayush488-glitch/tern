"""PermissionGate — the second of two gates (ADR-0003 §double-gate).

The registry filter (gate 1) trims the model's tool list. This gate runs at
call site: even if the tool is visible, the gate either approves, prompts,
or denies based on annotations + mode + a caller-supplied prompter.

Why two gates: registry-only leaks if the model coerces a tool name; call-site
only leaks via "I'll just describe what I would do" exfiltration. Both,
together, make the audit story honest.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel

from tern.tools.protocol import Tool, ToolContext


class Mode(str, Enum):
    """CLI propagated. ADR-0003 §modes.

    Stored as a string Enum so the value flows cleanly through ToolContext.mode
    (which is a plain str — keeps the dataclass JSON-serializable for replay).
    """

    SAFE = "safe"
    DEFAULT = "default"
    YOLO = "yolo"


class ApprovalDecision(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"


class ToolBlocked(Exception):
    """Raised when the gate refuses a call (denied OR mode-incompatible).

    Distinct from validation errors so the loop can branch: ToolBlocked closes
    the turn with `permission_denied`, validation errors trigger reflection.
    """


# A prompter is any async callable that asks the user (TUI in production,
# canned in tests). It receives the tool, its validated args, and the context;
# it returns a Decision. The gate orchestrates; the prompter chooses.
Prompter = Callable[[Tool, BaseModel, ToolContext], Awaitable[ApprovalDecision]]


@dataclass(frozen=True, slots=True)
class PermissionGate:
    """Runtime gate. Stateless apart from the prompter reference."""

    prompter: Prompter | None = None

    async def check(
        self,
        tool: Tool,
        args: BaseModel,
        ctx: ToolContext,
    ) -> ApprovalDecision:
        """Return GRANTED if the call may proceed; raise ToolBlocked otherwise.

        Side effect (intentional): prompts the user via `self.prompter` when the
        mode requires it. The prompter is async so the TUI can pop a modal.
        """
        # mode-incompatible: the call should not have reached here, but be
        # defensive in case a tool was added at runtime.
        if ctx.mode == Mode.SAFE.value and tool.annotations.destructive:
            raise ToolBlocked(
                f"tool {tool.name!r} is destructive; refused in safe mode"
            )
        if ctx.mode == Mode.YOLO.value:
            return ApprovalDecision.GRANTED

        # default mode: read-only / non-destructive go through; destructive prompt.
        if not tool.annotations.destructive:
            return ApprovalDecision.GRANTED

        if self.prompter is None:
            # No prompter wired (tests, headless): default-deny destructive calls.
            raise ToolBlocked(
                f"tool {tool.name!r} requires approval but no prompter is wired"
            )
        decision = await self.prompter(tool, args, ctx)
        if decision == ApprovalDecision.DENIED:
            raise ToolBlocked(f"user denied {tool.name!r}")
        return decision
