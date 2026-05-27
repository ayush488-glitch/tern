"""M11 observability tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tern.core.events import (
    ApprovalGranted,
    ApprovalRequested,
    LLMRequested,
    LLMResponded,
    ReflectionTriggered,
    ToolCalled,
    ToolReturned,
    TurnCompleted,
    TurnStarted,
)
from tern.obs.recorder import SpanRecorder
from tern.obs.render import forest_to_str
from tern.obs.replay import replay_to_recorder
from tern.obs.sink import NDJSONSpanSink


@pytest.fixture
def fake_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    return "abcdef0123456789"


def _fake_turn_events(session_id: str) -> list:
    """A small but representative event stream:

    TurnStarted
      LLMRequested → LLMResponded
      ToolCalled → ApprovalRequested → ApprovalGranted → ToolReturned
      ReflectionTriggered (singleton)
      LLMRequested → LLMResponded
    TurnCompleted
    """
    ts = TurnStarted(session_id=session_id, turn_idx=0)
    llm1_req = LLMRequested(model_id="anthropic.claude-sonnet-4", n_messages=2, n_tools=1, parent_id=ts.id)
    llm1_res = LLMResponded(model_id="anthropic.claude-sonnet-4", tokens_in=120, tokens_out=40, cost_usd=0.0042, parent_id=llm1_req.id)
    tool_call = ToolCalled(tool_name="edit_block", call_id="c1", args_preview="path=foo.py", parent_id=ts.id)
    appr_req = ApprovalRequested(tool_name="edit_block", call_id="c1", reason="destructive", parent_id=tool_call.id)
    appr_grant = ApprovalGranted(tool_name="edit_block", call_id="c1", parent_id=appr_req.id)
    tool_ret = ToolReturned(tool_name="edit_block", call_id="c1", ok=True, bytes_out=512, parent_id=tool_call.id)
    refl = ReflectionTriggered(depth=1, cause="lint_error", parent_id=ts.id)
    llm2_req = LLMRequested(model_id="anthropic.claude-sonnet-4", n_messages=4, n_tools=1, parent_id=ts.id)
    llm2_res = LLMResponded(model_id="anthropic.claude-sonnet-4", tokens_in=180, tokens_out=10, cost_usd=0.0021, parent_id=llm2_req.id, stop_reason="end_turn")
    tc = TurnCompleted(reason="done", parent_id=ts.id)
    return [ts, llm1_req, llm1_res, tool_call, appr_req, appr_grant, tool_ret, refl, llm2_req, llm2_res, tc]


def test_recorder_pairs_open_close(fake_session: str) -> None:
    rec = SpanRecorder()
    for ev in _fake_turn_events(fake_session):
        rec.consume(ev)

    # One root: TurnStarted.
    assert len(rec.roots) == 1
    turn = rec.roots[0]
    assert turn.kind == "turn_started"

    # Children attached under the turn span (in order):
    #   llm1, tool_call, reflection (singleton), llm2, turn_completed (singleton)
    kinds = [c.kind for c in turn.children]
    assert kinds == [
        "llm_requested",
        "tool_called",
        "reflection_triggered",
        "llm_requested",
        "turn_completed",
    ]

    # llm1 closed, with cost.
    llm1 = turn.children[0]
    assert llm1.is_closed
    assert llm1.duration_ns is not None and llm1.duration_ns >= 0

    # tool_call has approval-pair as a nested child.
    tool = turn.children[1]
    assert tool.is_closed
    assert any(c.kind == "approval_requested" and c.is_closed for c in tool.children)

    # Total cost = 0.0042 + 0.0021.
    assert abs(rec.total_cost_usd() - 0.0063) < 1e-9


def test_recorder_handles_open_spans(fake_session: str) -> None:
    """If the stream ends mid-pair, the recorder leaves it open — no fake closer."""
    rec = SpanRecorder()
    rec.consume(TurnStarted(session_id=fake_session))
    rec.consume(LLMRequested(model_id="x"))
    # No LLMResponded — simulates an aborted turn.
    assert len(rec.roots) == 1
    turn = rec.roots[0]
    open_child = turn.children[0]
    assert open_child.kind == "llm_requested"
    assert not open_child.is_closed
    assert open_child.duration_ns is None


def test_ndjson_sink_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_session: str) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    sink = NDJSONSpanSink(session_id=fake_session)
    rec = SpanRecorder(sink=sink)
    for ev in _fake_turn_events(fake_session):
        rec.consume(ev)

    # File exists, has the right number of lines.
    assert sink.path.exists()
    n_lines = sum(1 for _ in sink.path.open())
    assert n_lines == 11

    # Replay reconstructs the same tree.
    rec2 = replay_to_recorder(sink.path)
    assert len(rec2.roots) == 1
    turn = rec2.roots[0]
    assert [c.kind for c in turn.children] == [
        "llm_requested",
        "tool_called",
        "reflection_triggered",
        "llm_requested",
        "turn_completed",
    ]
    assert abs(rec2.total_cost_usd() - 0.0063) < 1e-9


def test_render_produces_readable_text(fake_session: str) -> None:
    rec = SpanRecorder()
    for ev in _fake_turn_events(fake_session):
        rec.consume(ev)
    text = forest_to_str(rec.roots, title="test")
    # Spot-check key labels appear.
    assert "test" in text
    assert "turn 0" in text
    assert "llm anthropic.claude-sonnet-4" in text
    assert "tool edit_block ✓" in text
    assert "approval_requested" in text
    assert "reflection_triggered" in text


def test_paths_isolated_per_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    sub_a = tmp_path / "proj-a"
    sub_b = tmp_path / "proj-b"
    sub_a.mkdir()
    sub_b.mkdir()
    p_a = NDJSONSpanSink(session_id="s1", cwd=sub_a).path
    p_b = NDJSONSpanSink(session_id="s1", cwd=sub_b).path
    assert p_a != p_b
    assert tmp_path in p_a.parents
    assert tmp_path in p_b.parents
