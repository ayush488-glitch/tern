"""M1 — the agent turn loop.

One turn yields events. No mutable state on self; the Turn is the input.

S9 shape:

    TurnStarted
    └── step 0
         LLMRequested → LLMResponded
         (for each tool_use block:)
              [ApprovalRequested → ApprovalGranted/Denied]
              ToolCalled → ToolReturned
              (or ReflectionTriggered if the model produced bad args)
    └── step 1, 2 ...  (until end_turn or max_steps)
    TurnCompleted

Per ADR-0002: the loop knows about canonical types, the ProviderAdapter Protocol,
and the M5 tool surface. It does NOT know about any concrete provider, the TUI,
or the recorder. Those are downstream consumers of the same event stream.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace as dc_replace

from pydantic import ValidationError

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    lift_pseudo_xml_tool_calls,
)
from tern.core.events import (
    ApprovalDenied,
    ApprovalGranted,
    ApprovalRequested,
    LLMRequested,
    LLMResponded,
    LLMTextDelta,
    ReflectionTriggered,
    ToolCalled,
    ToolReturned,
    TurnCompleted,
    TurnEvent,
    TurnStarted,
)
from tern.core.provider import ProviderAdapter
from tern.core.turn import Turn
from tern.tools import (
    ApprovalDecision,
    PermissionGate,
    Registry,
    Tool,
    ToolBlocked,
    ToolContext,
    ToolResult,
)


async def run_turn(turn: Turn, adapter: ProviderAdapter) -> AsyncIterator[TurnEvent]:
    """Execute one turn. Yield events as they happen.

    The caller decides what to do with events — render, persist, both, neither.
    The loop never persists or prints; it only emits.
    """
    started = TurnStarted(session_id=turn.session_id, turn_idx=turn.idx)
    yield started

    registry = turn.registry or Registry()
    gate = turn.gate or PermissionGate()
    tool_specs = registry.specs(mode=turn.mode)

    messages: tuple[CanonicalMessage, ...] = turn.messages
    completion_reason: str = "done"

    for _step in range(turn.max_steps):
        requested = LLMRequested(
            parent_id=started.id,
            model_id=adapter.model_id,
            routing_purpose=turn.purpose.value,
            n_messages=len(messages),
            n_tools=len(tool_specs),
        )
        yield requested

        if hasattr(adapter, "stream"):
            response = None
            async for ev in adapter.stream(
                messages=messages,
                tools=tool_specs,
                max_tokens=turn.max_tokens,
                temperature=turn.temperature,
            ):
                kind, payload = ev
                if kind == "text":
                    yield LLMTextDelta(parent_id=requested.id, text=payload)
                elif kind == "done":
                    response = payload
            if response is None:
                # adapter implemented stream() but never yielded "done";
                # treat as provider error and end the turn.
                completion_reason = "provider_error"
                break
        else:
            response = await adapter.complete(
                messages=messages,
                tools=tool_specs,
                max_tokens=turn.max_tokens,
                temperature=turn.temperature,
            )

        yield LLMResponded(
            parent_id=requested.id,
            model_id=adapter.model_id,
            tokens_in=response.cost.input_tokens,
            tokens_out=response.cost.output_tokens,
            cost_usd=response.cost.usd_total,
            stop_reason=response.stop_reason or "end_turn",
        )

        # Rescue: some models emit `<tool_name>...</tool_name>` text instead
        # of a structured tool_use block. Lift those into ToolCallBlocks so
        # the loop can fire them. Idempotent + scoped to registered tools.
        allowed = frozenset(t.name for t in registry.visible_to_model(mode=turn.mode))
        rescued = lift_pseudo_xml_tool_calls(response.message, allowed)

        # Append the (possibly rewritten) assistant message to the rolling log.
        messages = (*messages, rescued)

        tool_calls = tuple(
            b for b in rescued.content if isinstance(b, ToolCallBlock)
        )
        stop_reason = response.stop_reason or "end_turn"

        if not tool_calls:
            # No tool blocks → assistant produced a final message. Done.
            completion_reason = (
                "max_steps" if stop_reason == "max_tokens" else "done"
            )
            break

        # ---- execute every tool block, accumulate tool_result blocks ------
        tool_result_blocks: list[ToolResultBlock] = []
        ctx = ToolContext(
            repo_root=turn.repo_root,
            session_id=turn.session_id,
            turn_idx=turn.idx,
            mode=turn.mode,
        )

        denied = False
        for call in tool_calls:
            tool = registry.get(call.name)
            if tool is None:
                # Unknown tool — feed the error back so the model can retry.
                tool_result_blocks.append(
                    ToolResultBlock(
                        call_id=call.id,
                        ok=False,
                        content="",
                        error=f"unknown tool: {call.name!r}",
                    )
                )
                yield ReflectionTriggered(
                    parent_id=started.id,
                    depth=1,
                    cause=f"unknown_tool:{call.name}",
                )
                continue

            # Validate args. ValidationError → reflection retry input.
            try:
                args = tool.args_model.model_validate(call.args)
            except ValidationError as exc:
                tool_result_blocks.append(
                    ToolResultBlock(
                        call_id=call.id,
                        ok=False,
                        content="",
                        error=f"invalid arguments: {exc.errors()}",
                    )
                )
                yield ReflectionTriggered(
                    parent_id=started.id,
                    depth=1,
                    cause="validation_error",
                )
                continue

            # Permission gate (gate 2 — call-site).
            try:
                async for ev in _run_gate(gate, tool, args, ctx, call.id):
                    yield ev
            except ToolBlocked as exc:
                tool_result_blocks.append(
                    ToolResultBlock(
                        call_id=call.id,
                        ok=False,
                        content="",
                        error=str(exc),
                    )
                )
                # If the user explicitly denied, close the turn after we
                # finish the current batch.
                if "user denied" in str(exc) or "refused in safe mode" in str(exc):
                    denied = True
                continue

            # Invoke.
            yield ToolCalled(
                parent_id=started.id,
                tool_name=tool.name,
                call_id=call.id,
                args_preview=_args_preview(call.args),
            )
            result: ToolResult = await tool.invoke(args, ctx)
            yield ToolReturned(
                parent_id=started.id,
                tool_name=tool.name,
                call_id=call.id,
                ok=result.ok,
                bytes_out=len(result.content),
                error=result.error,
            )
            tool_result_blocks.append(
                ToolResultBlock(
                    call_id=call.id,
                    ok=result.ok,
                    content=result.content if result.ok else (result.error or ""),
                    error=result.error,
                )
            )

        # Append tool results as a single role="tool" message and keep going.
        messages = (
            *messages,
            CanonicalMessage(
                role="tool",
                content=tuple(tool_result_blocks),
                metadata=Metadata(
                    schema_version=SCHEMA_VERSION, ts=0.0, provenance="tool"
                ),
            ),
        )

        if denied:
            completion_reason = "permission_denied"
            break
    else:
        # for/else: ran out of steps without breaking.
        completion_reason = "max_steps"

    yield TurnCompleted(reason=completion_reason)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _run_gate(
    gate: PermissionGate,
    tool: Tool,
    args: object,  # validated pydantic BaseModel; typed object to dodge invariance
    ctx: ToolContext,
    call_id: str,
) -> AsyncIterator[TurnEvent]:
    """Run the permission gate and emit approval-pair events.

    For non-destructive tools the gate auto-approves silently — no events
    emitted (would just be noise in the span tree). Destructive tools always
    emit ApprovalRequested + Granted/Denied.
    """
    if not tool.annotations.destructive:
        # Non-destructive: gate still validates safe-mode etc., but we don't
        # bother with approval-pair events.
        await gate.check(tool, args, ctx)  # type: ignore[arg-type]
        return

    yield ApprovalRequested(
        tool_name=tool.name,
        call_id=call_id,
        reason="destructive",
    )
    try:
        decision = await gate.check(tool, args, ctx)  # type: ignore[arg-type]
    except ToolBlocked as exc:
        yield ApprovalDenied(
            tool_name=tool.name,
            call_id=call_id,
            reason=str(exc),
        )
        raise
    if decision == ApprovalDecision.GRANTED:
        yield ApprovalGranted(tool_name=tool.name, call_id=call_id)


def _args_preview(args: dict[str, object], cap: int = 80) -> str:
    """Truncated repr of args for the span line. Full args live in the canonical log."""
    s = json.dumps(args, default=str, sort_keys=True)
    return s if len(s) <= cap else s[: cap - 1] + "…"


# Imported for tests that patch it; keep visible but unused otherwise.
__all__ = ["TextBlock", "dc_replace", "run_turn"]
