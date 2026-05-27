"""M1 — the agent turn loop.

One turn yields events. No mutable state on self; the Turn is the input.

For S8 the loop is intentionally minimal:
  TurnStarted -> LLMRequested -> (await adapter.complete) -> LLMResponded -> TurnCompleted

S9 layers tools on top of this. S10 layers session/replay. The shape stays
the same: an async generator over TurnEvents.

Per ADR-0002: the loop knows about canonical types and the ProviderAdapter
Protocol; it does NOT know about any concrete provider, the TUI, or the
recorder. Those are downstream consumers of the same event stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from tern.core.events import (
    LLMRequested,
    LLMResponded,
    TurnCompleted,
    TurnEvent,
    TurnStarted,
)
from tern.core.provider import ProviderAdapter
from tern.core.turn import Turn

_STOP_REASON_TO_COMPLETION: dict[
    str,
    str,
] = {
    "end_turn": "done",
    "max_tokens": "max_steps",
    "stop_sequence": "done",
    "tool_use": "done",  # S9 will branch here instead
}


async def run_turn(turn: Turn, adapter: ProviderAdapter) -> AsyncIterator[TurnEvent]:
    """Execute one turn. Yield events as they happen.

    The caller decides what to do with events — render, persist, both, neither.
    The loop never persists or prints; it only emits.
    """
    started = TurnStarted(session_id=turn.session_id, turn_idx=turn.idx)
    yield started

    requested = LLMRequested(
        parent_id=started.id,
        model_id=adapter.model_id,
        routing_purpose=turn.purpose.value,
        n_messages=len(turn.messages),
        n_tools=0,
    )
    yield requested

    response = await adapter.complete(
        messages=turn.messages,
        tools=(),
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

    completion_reason = _STOP_REASON_TO_COMPLETION.get(response.stop_reason or "end_turn", "done")
    yield TurnCompleted(reason=completion_reason)  # type: ignore[arg-type]
