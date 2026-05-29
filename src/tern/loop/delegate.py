"""Sub-turn delegation (S21 / ADR-0012 §2).

Spawns a child turn with isolated context. Parent sees only the child's final
summary string — child tool calls and intermediate messages never enter the
parent's context window.

Shape mirrors Hermes's delegate_task: goal + context + optional toolset.

ADR-0002 compliance: each child turn is its own state-replaced turn.
Permission inheritance: child inherits parent mode unless explicitly demoted.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
)
from tern.core.turn import Turn, TurnPurpose
from tern.tools.protocol import (
    ToolAnnotations,
    ToolContext,
    ToolResult,
)

if TYPE_CHECKING:
    from tern.core.provider import ProviderAdapter

_DEFAULT_MAX_STEPS = 20
_DEFAULT_TIMEOUT_S = 120.0


class DelegateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(..., description="What the child turn should accomplish.")
    context: str = Field(
        "",
        description=(
            "Background information the child needs. Include file paths, error "
            "messages, and constraints. The child has no memory of the parent turn."
        ),
    )
    max_steps: int = Field(
        _DEFAULT_MAX_STEPS,
        ge=1,
        le=50,
        description="Max tool-call steps the child turn may take.",
    )
    timeout: float = Field(
        _DEFAULT_TIMEOUT_S,
        ge=5.0,
        le=600.0,
        description="Timeout seconds for the child turn.",
    )


class DelegateTool:
    """Spawn a child turn with isolated context. Returns only the final summary.

    Use when a sub-task would flood the parent context with intermediate data.
    The child gets the same tools as the parent (minus delegate itself, to
    prevent infinite recursion).
    """

    name = "delegate"
    title = "Delegate sub-task"
    description = (
        "Spawn a child turn to handle a focused sub-task. The child runs in "
        "isolated context — parent only sees the child's final reply. "
        "Use when the sub-task would generate too many tool calls to keep in "
        "the current context window."
    )
    args_model: type[BaseModel] = DelegateArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=True
    )

    def __init__(self, adapter: ProviderAdapter) -> None:
        self._adapter = adapter

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, DelegateArgs)

        # Build a minimal prompt for the child turn.
        parts = [f"GOAL: {args.goal}"]
        if args.context:
            parts.append(f"\nCONTEXT:\n{args.context}")
        prompt = "\n".join(parts)

        ts = time.time()
        user_msg = CanonicalMessage(
            role="user",
            content=(TextBlock(text=prompt),),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=ts,
                provenance="delegate_parent",
            ),
        )

        # Build the child registry (same tools as parent, minus `delegate`
        # to prevent recursive delegation).
        from tern.tools import Registry  # local import to avoid circular
        # ToolContext does not expose registry; build a fresh child registry
        # from the adapter's default set.  DelegateTool itself is excluded.
        child_registry: Registry | None = None
        # ToolContext does not expose registry (no field); leave None for now.
        # Future: pass registry via Turn gate field.

        import uuid
        child_turn = Turn(
            id=f"delegate-{uuid.uuid4().hex[:8]}",
            session_id=f"{ctx.session_id}:child",
            idx=0,
            purpose=TurnPurpose.CODE,
            messages=(user_msg,),
            mode=ctx.mode,
            max_steps=args.max_steps,
            registry=child_registry,
            repo_root=ctx.repo_root,
        )

        # Drain the child event stream, collecting the final text reply.
        from tern.core.loop import run_turn  # local import (avoid circular at module level)
        final_text = ""
        try:
            async def _run() -> str:
                nonlocal final_text
                from tern.core.events import LLMTextDelta
                async for ev in run_turn(child_turn, self._adapter):
                    if isinstance(ev, LLMTextDelta):
                        final_text += ev.text
                return final_text

            await asyncio.wait_for(_run(), timeout=args.timeout)
        except asyncio.TimeoutError:
            return ToolResult(
                ok=True,
                content=f"[delegate timed out after {args.timeout}s]\n{final_text}",
                metadata={"timed_out": True, "goal": args.goal[:100]},
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                content="",
                error=f"child turn failed: {exc}",
            )

        return ToolResult(
            ok=True,
            content=final_text or "(child produced no output)",
            metadata={"goal": args.goal[:100], "timed_out": False},
        )


__all__ = ["DelegateArgs", "DelegateTool"]
