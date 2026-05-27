"""S15 — self-curation v0 nudge queue."""

from __future__ import annotations

import pytest

from tern.memory.curate import TurnSignal, maybe_queue_nudge, read_queue


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    yield


def _signal(**kw):
    base = dict(
        session_id="s1",
        tool_names=("read_file",),
        tool_calls=1,
        error_count=0,
        user_text="hi",
    )
    base.update(kw)
    return TurnSignal(**base)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.delenv("TERN_AUTO_CURATE", raising=False)
    assert maybe_queue_nudge(_signal(user_text="please remember this fact")) is None
    assert read_queue() == []


def test_user_cue_triggers(monkeypatch):
    monkeypatch.setenv("TERN_AUTO_CURATE", "1")
    hint = maybe_queue_nudge(_signal(user_text="please remember this preference"))
    assert hint and "user-cue" in hint
    q = read_queue()
    assert len(q) == 1
    assert q[0]["session_id"] == "s1"


def test_long_success_triggers(monkeypatch):
    monkeypatch.setenv("TERN_AUTO_CURATE", "1")
    hint = maybe_queue_nudge(_signal(
        tool_names=("read_file", "write_file", "bash"),
        tool_calls=6, error_count=0, user_text="just do it",
    ))
    assert hint and "procedure" in hint


def test_error_recovery_triggers(monkeypatch):
    monkeypatch.setenv("TERN_AUTO_CURATE", "1")
    hint = maybe_queue_nudge(_signal(
        tool_calls=3, error_count=1, user_text="ok thanks",
    ))
    assert hint and "pitfall" in hint


def test_boring_turn_does_not_trigger(monkeypatch):
    monkeypatch.setenv("TERN_AUTO_CURATE", "1")
    assert maybe_queue_nudge(_signal()) is None
    assert read_queue() == []
