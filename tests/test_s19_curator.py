"""Tests for S19 — curator subsystem (OutcomeSpan, curate.py, tern curate)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


# ─── helpers ──────────────────────────────────────────────────────────────────

def _fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake git repo for testing."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    git = tmp_path / ".git"
    git.mkdir()
    return tmp_path


def _set_tern_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "tern_home"
    home.mkdir()
    monkeypatch.setenv("TERN_HOME", str(home))
    return home


# ─── OutcomeSpan event ────────────────────────────────────────────────────────

def test_outcome_span_defaults() -> None:
    from tern.core.events import OutcomeSpan

    span = OutcomeSpan()
    assert span.kind == "outcome_span"
    assert span.tests_passed is None
    assert span.commit_landed is None
    assert span.user_correction is False
    assert span.tool_names == ()
    assert span.error_count == 0


def test_outcome_span_in_turn_event_union() -> None:
    """OutcomeSpan must be part of TurnEvent so the recorder accepts it."""
    from tern.core.events import OutcomeSpan, TurnEvent
    import typing

    args = typing.get_args(TurnEvent)
    assert OutcomeSpan in args


def test_outcome_span_frozen() -> None:
    from tern.core.events import OutcomeSpan

    span = OutcomeSpan(purpose="code")
    with pytest.raises((AttributeError, TypeError)):
        span.purpose = "arch"  # type: ignore[misc]


# ─── detect_tests_passed ─────────────────────────────────────────────────────

def test_detect_tests_passed_positive() -> None:
    from tern.memory.curate import detect_tests_passed

    assert detect_tests_passed(["42 passed in 1.23s"]) is True


def test_detect_tests_passed_fail() -> None:
    from tern.memory.curate import detect_tests_passed

    assert detect_tests_passed(["2 failed, 40 passed in 2.1s"]) is False


def test_detect_tests_passed_only_fail() -> None:
    from tern.memory.curate import detect_tests_passed

    assert detect_tests_passed(["1 failed in 0.5s"]) is False


def test_detect_tests_passed_none() -> None:
    from tern.memory.curate import detect_tests_passed

    assert detect_tests_passed(["some random output"]) is None


def test_detect_tests_passed_empty() -> None:
    from tern.memory.curate import detect_tests_passed

    assert detect_tests_passed([]) is None


# ─── detect_commit_landed ────────────────────────────────────────────────────

def test_detect_commit_landed_positive() -> None:
    from tern.memory.curate import detect_commit_landed

    assert detect_commit_landed(["[main 4a3b12c] session: S19"]) is True


def test_detect_commit_landed_none() -> None:
    from tern.memory.curate import detect_commit_landed

    assert detect_commit_landed(["nothing here"]) is None


# ─── is_correction ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "no, actually that's wrong",
    "undo that last change",
    "that didn't work",
    "try again please",
    "incorrect approach",
])
def test_is_correction_true(text: str) -> None:
    from tern.memory.curate import is_correction

    assert is_correction(text) is True


def test_is_correction_false() -> None:
    from tern.memory.curate import is_correction

    assert is_correction("looks good, thanks") is False


# ─── OutcomeRecord + log_outcome + read_outcomes ──────────────────────────────

def test_log_and_read_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    from tern.memory.curate import OutcomeRecord, log_outcome, read_outcomes

    rec = OutcomeRecord(
        session_id="sess-abc",
        ts=time.time(),
        purpose="code",
        model_id="sonnet",
        tool_names=("bash", "write_file"),
        error_count=0,
        prompt_preview="fix the bug",
        tests_passed=True,
        commit_landed=True,
        user_correction=False,
    )
    log_outcome(rec)
    results = read_outcomes()
    assert len(results) == 1
    r = results[0]
    assert r.session_id == "sess-abc"
    assert r.purpose == "code"
    assert r.tests_passed is True
    assert r.commit_landed is True
    assert "bash" in r.tool_names


def test_read_outcomes_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    from tern.memory.curate import read_outcomes

    assert read_outcomes() == []


def test_read_outcomes_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    from tern.memory.curate import OutcomeRecord, log_outcome, read_outcomes

    for i in range(10):
        log_outcome(OutcomeRecord(
            session_id=f"s{i}",
            ts=float(i),
            purpose="code",
            model_id="m",
            tool_names=(),
            error_count=0,
            prompt_preview="p",
            tests_passed=None,
            commit_landed=None,
            user_correction=False,
        ))
    results = read_outcomes(limit=3)
    assert len(results) == 3
    # should be the last 3 (most recent)
    assert results[-1].session_id == "s9"


# ─── CurationProposal + distill_proposals ─────────────────────────────────────

def test_distill_proposals_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    repo = _fake_repo(tmp_path / "repo")
    from tern.memory.curate import distill_proposals

    proposals = distill_proposals(repo)
    # No queue, no outcomes — expect empty
    assert proposals == []


def test_distill_from_queue_pitfall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    monkeypatch.setenv("TERN_AUTO_CURATE", "1")
    repo = _fake_repo(tmp_path / "repo")

    # Seed the queue manually
    from tern.memory.curate import _queue_path  # type: ignore[attr-defined]
    row = {"ts": time.time(), "session_id": "s1", "hint": "pitfall: mypy barfs on bare float()", "tool_calls": 3, "errors": 1}
    _queue_path().write_text(json.dumps(row) + "\n", encoding="utf-8")

    from tern.memory.curate import distill_proposals

    proposals = distill_proposals(repo)
    assert any(p.target == "failures" for p in proposals)
    pitfall_props = [p for p in proposals if p.target == "failures"]
    assert "mypy barfs" in pitfall_props[0].content


def test_distill_from_queue_procedure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    repo = _fake_repo(tmp_path / "repo")

    from tern.memory.curate import _queue_path  # type: ignore[attr-defined]
    row = {"ts": time.time(), "session_id": "s1", "hint": "procedure: 7 tool calls succeeded (bash, write_file) — consider as skill", "tool_calls": 7, "errors": 0}
    _queue_path().write_text(json.dumps(row) + "\n", encoding="utf-8")

    from tern.memory.curate import distill_proposals

    proposals = distill_proposals(repo)
    assert any(p.target == "decisions" for p in proposals)


def test_distill_from_outcome_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    repo = _fake_repo(tmp_path / "repo")

    from tern.memory.curate import OutcomeRecord, log_outcome

    for i in range(3):
        log_outcome(OutcomeRecord(
            session_id=f"s{i}",
            ts=float(time.time() + i),
            purpose="code",
            model_id="sonnet",
            tool_names=(),
            error_count=2,
            prompt_preview=f"turn {i}",
            tests_passed=False,
            commit_landed=None,
            user_correction=False,
        ))

    from tern.memory.curate import distill_proposals

    proposals = distill_proposals(repo)
    failure_props = [p for p in proposals if p.target == "failures"]
    assert len(failure_props) >= 1
    assert "tests_passed=False" in failure_props[0].reason


def test_distill_from_correction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    repo = _fake_repo(tmp_path / "repo")

    from tern.memory.curate import OutcomeRecord, log_outcome

    log_outcome(OutcomeRecord(
        session_id="s1",
        ts=time.time(),
        purpose="arch",
        model_id="opus",
        tool_names=(),
        error_count=0,
        prompt_preview="design the system",
        tests_passed=None,
        commit_landed=None,
        user_correction=True,  # user corrected the turn
    ))

    from tern.memory.curate import distill_proposals

    proposals = distill_proposals(repo)
    corr_props = [p for p in proposals if "correction" in p.reason]
    assert len(corr_props) >= 1
    assert corr_props[0].target == "failures"


# ─── apply_proposal ───────────────────────────────────────────────────────────

def test_apply_proposal_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    repo = _fake_repo(tmp_path / "repo")

    from tern.memory.curate import CurationProposal, apply_proposal
    from tern.memory.repo_store import load_repo_memory

    prop = CurationProposal(
        id="abc123",
        ts=time.time(),
        target="failures",
        action="add",
        content="mypy strict fails on bare Any return",
        old_text="",
        reason="test",
        source="manual",
    )
    apply_proposal(repo, prop)

    entries, raw = load_repo_memory("failures", repo)
    assert "mypy strict fails" in raw or any("mypy strict fails" in e for e in entries)


def test_apply_proposal_unknown_target(tmp_path: Path) -> None:
    from tern.memory.curate import CurationProposal, apply_proposal

    prop = CurationProposal(
        id="bad",
        ts=time.time(),
        target="unknown",  # type: ignore[arg-type]
        action="add",
        content="oops",
        old_text="",
        reason="test",
        source="manual",
    )
    with pytest.raises(ValueError, match="unknown target"):
        apply_proposal(tmp_path, prop)


def test_apply_proposal_replace_missing_old_text(tmp_path: Path) -> None:
    from tern.memory.curate import CurationProposal, apply_proposal

    prop = CurationProposal(
        id="bad",
        ts=time.time(),
        target="arch",
        action="replace",
        content="new",
        old_text="",  # empty — should raise
        reason="test",
        source="manual",
    )
    with pytest.raises(ValueError, match="non-empty old_text"):
        apply_proposal(tmp_path, prop)


# ─── read_proposals + clear_proposals ────────────────────────────────────────

def test_read_and_clear_proposals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tern_home(tmp_path, monkeypatch)
    repo = _fake_repo(tmp_path / "repo")

    from tern.memory.curate import _queue_path  # type: ignore[attr-defined]
    row = {"ts": time.time(), "session_id": "s1", "hint": "pitfall: ruff won't --fix inline", "tool_calls": 2, "errors": 1}
    _queue_path().write_text(json.dumps(row) + "\n", encoding="utf-8")

    from tern.memory.curate import clear_proposals, distill_proposals, read_proposals

    distill_proposals(repo)
    props = read_proposals(repo)
    assert len(props) >= 1

    clear_proposals(repo)
    assert read_proposals(repo) == []
