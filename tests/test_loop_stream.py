"""Loop streaming path: when adapter has stream(), text deltas are emitted."""
from __future__ import annotations

import pytest

from tern.core.canonical import SCHEMA_VERSION, CanonicalMessage, Metadata, TextBlock
from tern.core.events import LLMResponded, LLMTextDelta, TurnCompleted
from tern.core.loop import run_turn
from tern.core.turn import Turn, TurnPurpose
from tests._fakes import FakeStreamingAdapter


def _user_msg(text: str) -> CanonicalMessage:
    return CanonicalMessage(
        role="user",
        content=(TextBlock(text=text),),
        metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="user"),
    )


@pytest.mark.asyncio
async def test_streaming_emits_text_deltas() -> None:
    adapter = FakeStreamingAdapter(reply="hi!", model_id="fake-stream")
    turn = Turn(
        id="t-stream-1",
        session_id="s1",
        idx=0,
        purpose=TurnPurpose.CODE,
        messages=(_user_msg("yo"),),
        max_steps=2,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    kinds = [type(e).__name__ for e in events]
    # text deltas appear after LLMRequested, before LLMResponded
    assert "LLMRequested" in kinds and "LLMResponded" in kinds
    deltas = [e for e in events if isinstance(e, LLMTextDelta)]
    assert "".join(d.text for d in deltas) == "hi!"
    # ordering: LLMRequested -> deltas -> LLMResponded -> TurnCompleted
    req_i = kinds.index("LLMRequested")
    resp_i = kinds.index("LLMResponded")
    delta_idxs = [i for i, k in enumerate(kinds) if k == "LLMTextDelta"]
    assert all(req_i < i < resp_i for i in delta_idxs)
    assert isinstance(events[-1], TurnCompleted)
    assert events[-1].reason == "done"
    # parent_id of deltas points at the LLMRequested
    assert all(d.parent_id == events[req_i].id for d in deltas)
    # adapter.calls recorded "streamed": True
    assert adapter.calls[0]["streamed"] is True


@pytest.mark.asyncio
async def test_streaming_empty_reply_still_completes() -> None:
    adapter = FakeStreamingAdapter(reply="", model_id="fake-stream")
    turn = Turn(
        id="t-stream-2", session_id="s2", idx=0, purpose=TurnPurpose.CODE,
        messages=(_user_msg("yo"),), max_steps=2,
    )
    events = [ev async for ev in run_turn(turn, adapter)]
    assert any(isinstance(e, LLMResponded) for e in events)
    assert isinstance(events[-1], TurnCompleted)
