"""Tests for M1 — the agent turn loop.

Pins the event sequence and span tree shape for a single no-tools turn.

Event order for one turn with no tools:
    turn_started -> llm_requested -> llm_responded -> turn_completed

Span tree after recorder consumes all events:
    turn_started (root)
      llm_requested-llm_responded (sealed pair)
    turn_completed (root, singleton)
"""

from __future__ import annotations

import asyncio

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
)
from tern.core.events import (
    LLMRequested,
    LLMResponded,
    TurnCompleted,
    TurnStarted,
)
from tern.core.loop import run_turn
from tern.core.turn import Turn, TurnPurpose
from tern.obs.recorder import SpanRecorder
from tests._fakes import FakeAdapter


def _user(text: str) -> CanonicalMessage:
    return CanonicalMessage(
        role="user",
        content=(TextBlock(text=text),),
        metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
    )


def _drain(turn: Turn, adapter: FakeAdapter) -> list[object]:
    async def _run() -> list[object]:
        out: list[object] = []
        async for ev in run_turn(turn, adapter):
            out.append(ev)
        return out

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# event sequence
# ---------------------------------------------------------------------------


def test_run_turn_yields_expected_event_sequence() -> None:
    turn = Turn(
        id="t-1",
        session_id="s-1",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user("hi"),),
        max_tokens=128,
    )
    adapter = FakeAdapter(reply="hello back")

    events = _drain(turn, adapter)

    kinds = [type(ev).__name__ for ev in events]
    assert kinds == ["TurnStarted", "LLMRequested", "LLMResponded", "TurnCompleted"]


def test_turn_started_carries_session_and_idx() -> None:
    turn = Turn(
        id="t-2",
        session_id="sess-abc",
        idx=4,
        purpose=TurnPurpose.CODE,
        messages=(_user("hi"),),
        max_tokens=64,
    )
    events = _drain(turn, FakeAdapter())
    started = events[0]
    assert isinstance(started, TurnStarted)
    assert started.session_id == "sess-abc"
    assert started.turn_idx == 4


def test_llm_requested_describes_payload_size() -> None:
    turn = Turn(
        id="t-3",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user("a"), _user("b")),
        max_tokens=64,
    )
    events = _drain(turn, FakeAdapter())
    req = events[1]
    assert isinstance(req, LLMRequested)
    assert req.n_messages == 2
    assert req.n_tools == 0
    assert req.routing_purpose == "code"


def test_llm_responded_carries_cost_and_stop_reason() -> None:
    turn = Turn(
        id="t-4",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user("a"),),
        max_tokens=64,
    )
    events = _drain(turn, FakeAdapter())
    resp = events[2]
    assert isinstance(resp, LLMResponded)
    assert resp.tokens_in == 7
    assert resp.tokens_out == 3
    assert resp.stop_reason == "end_turn"


def test_turn_completed_reason_is_done_when_stop_reason_is_end_turn() -> None:
    turn = Turn(
        id="t-5",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user("a"),),
        max_tokens=64,
    )
    events = _drain(turn, FakeAdapter())
    completed = events[-1]
    assert isinstance(completed, TurnCompleted)
    assert completed.reason == "done"


# ---------------------------------------------------------------------------
# adapter is actually called with the right messages
# ---------------------------------------------------------------------------


def test_adapter_complete_is_called_with_turn_messages_and_max_tokens() -> None:
    turn = Turn(
        id="t-6",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user("calculate 2+2"),),
        max_tokens=256,
    )
    adapter = FakeAdapter()
    _drain(turn, adapter)
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call["messages"] == turn.messages
    assert call["max_tokens"] == 256


# ---------------------------------------------------------------------------
# events flow into the recorder cleanly (M11 integration)
# ---------------------------------------------------------------------------


def test_events_form_a_clean_span_tree_in_recorder() -> None:
    turn = Turn(
        id="t-7",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user("hi"),),
        max_tokens=64,
    )
    adapter = FakeAdapter()
    rec = SpanRecorder()

    async def _go() -> None:
        async for ev in run_turn(turn, adapter):
            rec.consume(ev)

    asyncio.run(_go())

    # turn_started is an opener (recorder treats it as one). It stays open
    # because nothing closes it. llm_requested opens under it and is sealed
    # by llm_responded. turn_completed is a singleton, attached as child of
    # the current top (the still-open turn_started span).
    assert len(rec.roots) == 1
    turn_root = rec.roots[0]
    assert turn_root.kind == "turn_started"
    assert len(turn_root.children) == 2
    llm = turn_root.children[0]
    assert llm.kind == "llm_requested"
    assert llm.closer is not None  # sealed
    assert turn_root.children[1].kind == "turn_completed"


# ---------------------------------------------------------------------------
# Turn dataclass surface
# ---------------------------------------------------------------------------


def test_turn_is_frozen() -> None:
    import dataclasses

    turn = Turn(
        id="t",
        session_id="s",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(),
        max_tokens=64,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        turn.idx = 1  # type: ignore[misc]


import pytest  # noqa: E402  (used in the last test only)
