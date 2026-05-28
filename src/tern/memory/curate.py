"""Self-curation v1 — outcome-span recorder + proposal distiller (S19).

Extends the v0 append-on-success hint queue with:

  1. OutcomeLogger  — appends one OutcomeSpan record to
     `~/.tern/memory/outcomes_log.jsonl` after each turn.
     Ground-truth signals: pytest exit in tool output, git commit exit,
     user-correction heuristic applied on the *following* turn.

  2. ProposalDistiller — reads curation_queue.jsonl + outcomes_log.jsonl,
     runs heuristics, produces typed diff-proposals into
     `<repo>/.tern/memory/curation_proposals.jsonl`.
     Never auto-applies — user reviews with `tern curate`.

  3. apply_proposal() — applies one accepted Proposal atomically via
     add_repo_entry / replace_repo_entry.

ADR-0002 sacred: nothing here mutates the canonical message log.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tern.obs.paths import tern_home

# ─── helpers ──────────────────────────────────────────────────────────────────

def _enabled() -> bool:
    return os.environ.get("TERN_AUTO_CURATE", "").strip() in ("1", "true", "yes")


def _queue_path() -> Path:
    d = tern_home() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "curation_queue.jsonl"


def _outcomes_path() -> Path:
    d = tern_home() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "outcomes_log.jsonl"


def _proposals_path(repo_root: Path) -> Path:
    d = repo_root / ".tern" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "curation_proposals.jsonl"


# ─── TurnSignal (v0 compat) ───────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TurnSignal:
    """Coarse summary of one turn for the curator's heuristics (v0 compat)."""

    session_id: str
    tool_names: tuple[str, ...]
    tool_calls: int
    error_count: int
    user_text: str


def _heuristic_hint(signal: TurnSignal) -> str | None:
    """Decide whether this turn earned a curation nudge."""
    low = signal.user_text.lower()
    triggers = ("remember", "don't do that again", "save this", "save that", "next time")
    if any(t in low for t in triggers):
        return f"user-cue: {signal.user_text.strip()[:200]}"
    if signal.tool_calls >= 5 and signal.error_count == 0:
        return (
            f"procedure: {signal.tool_calls} tool calls succeeded "
            f"({', '.join(sorted(set(signal.tool_names)))}) — consider as skill"
        )
    if signal.error_count >= 1 and signal.tool_calls > signal.error_count:
        return (
            f"pitfall: {signal.error_count} error(s) recovered from — "
            "consider logging the gotcha"
        )
    return None


def maybe_queue_nudge(signal: TurnSignal) -> str | None:
    """If gated on and heuristic fires, append one JSONL line. Returns hint or None."""
    if not _enabled():
        return None
    hint = _heuristic_hint(signal)
    if hint is None:
        return None
    record = {
        "ts": time.time(),
        "session_id": signal.session_id,
        "hint": hint,
        "tool_calls": signal.tool_calls,
        "errors": signal.error_count,
    }
    path = _queue_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return hint


def read_queue(limit: int = 20) -> list[dict[str, object]]:
    """Read the most recent N nudges (oldest first within the window)."""
    path = _queue_path()
    if not path.exists():
        return []
    lines = path.read_text("utf-8").splitlines()
    out: list[dict[str, object]] = []\

    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ─── OutcomeLogger (S19) ──────────────────────────────────────────────────────

# Patterns that suggest a user correction on the next turn.
_CORRECTION_PATTERNS = re.compile(
    r"\b(no[,.]?\s*actually|that'?s?\s*wrong|undo|revert|try again|"
    r"that didn'?t work|incorrect|not right|fix that|wrong approach)\b",
    re.IGNORECASE,
)

# Patterns that suggest pytest was run and its exit code.
_PYTEST_PASS = re.compile(r"\b(\d+)\s+passed\b", re.IGNORECASE)
_PYTEST_FAIL = re.compile(r"\b(\d+)\s+failed\b", re.IGNORECASE)

# Pattern that suggests a git commit succeeded.
_GIT_COMMIT_OK = re.compile(r"\[[\w/\-]+\s+[0-9a-f]{6,}\]", re.IGNORECASE)


def detect_tests_passed(tool_outputs: list[str]) -> bool | None:
    """Return True/False if pytest output found, None if not detected."""
    for out in tool_outputs:
        if _PYTEST_PASS.search(out):
            return not bool(_PYTEST_FAIL.search(out))
        if _PYTEST_FAIL.search(out):
            return False
    return None


def detect_commit_landed(tool_outputs: list[str]) -> bool | None:
    """Return True if git commit success pattern found, None otherwise."""
    for out in tool_outputs:
        if _GIT_COMMIT_OK.search(out):
            return True
    return None


def is_correction(text: str) -> bool:
    """Return True if the user text looks like a correction."""
    return bool(_CORRECTION_PATTERNS.search(text))


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """Serialisable record stored in outcomes_log.jsonl."""

    session_id: str
    ts: float
    purpose: str
    model_id: str
    tool_names: tuple[str, ...]
    error_count: int
    prompt_preview: str
    tests_passed: bool | None
    commit_landed: bool | None
    user_correction: bool


def log_outcome(record: OutcomeRecord) -> None:
    """Append one outcome record to outcomes_log.jsonl (always, not gated)."""
    path = _outcomes_path()
    row = {
        "session_id": record.session_id,
        "ts": record.ts,
        "purpose": record.purpose,
        "model_id": record.model_id,
        "tool_names": list(record.tool_names),
        "error_count": record.error_count,
        "prompt_preview": record.prompt_preview,
        "tests_passed": record.tests_passed,
        "commit_landed": record.commit_landed,
        "user_correction": record.user_correction,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_outcomes(limit: int = 100) -> list[OutcomeRecord]:
    """Read up to limit most recent outcome records."""
    path = _outcomes_path()
    if not path.exists():
        return []
    records: list[OutcomeRecord] = []
    for line in path.read_text("utf-8").splitlines()[-limit:]:
        try:
            d = json.loads(line)
            records.append(OutcomeRecord(
                session_id=str(d.get("session_id", "")),
                ts=float(str(d.get("ts", 0.0))),
                purpose=str(d.get("purpose", "")),
                model_id=str(d.get("model_id", "")),
                tool_names=tuple(str(x) for x in d.get("tool_names", [])),
                error_count=int(str(d.get("error_count", 0))),
                prompt_preview=str(d.get("prompt_preview", "")),
                tests_passed=d.get("tests_passed"),
                commit_landed=d.get("commit_landed"),
                user_correction=bool(d.get("user_correction", False)),
            ))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return records


# ─── CurationProposal (S19) ───────────────────────────────────────────────────

ProposalTarget = Literal["arch", "decisions", "failures", "reviewers"]


@dataclass(frozen=True, slots=True)
class CurationProposal:
    """One proposed diff to a repo memory target.

    `action` is "add" (new entry) or "replace" (update existing via old_text).
    """

    id: str
    ts: float
    target: ProposalTarget
    action: Literal["add", "replace"]
    content: str         # the entry text to add or the new text for replace
    old_text: str        # non-empty only when action=="replace"
    reason: str          # why this proposal was generated
    source: str          # "queue" | "outcome" | "manual"


def _write_proposal(path: Path, proposal: CurationProposal) -> None:
    row = {
        "id": proposal.id,
        "ts": proposal.ts,
        "target": proposal.target,
        "action": proposal.action,
        "content": proposal.content,
        "old_text": proposal.old_text,
        "reason": proposal.reason,
        "source": proposal.source,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_proposals(repo_root: Path) -> list[CurationProposal]:
    """Read all pending proposals for this repo (oldest first)."""
    path = _proposals_path(repo_root)
    if not path.exists():
        return []
    props: list[CurationProposal] = []
    for line in path.read_text("utf-8").splitlines():
        try:
            d = json.loads(line)
            props.append(CurationProposal(
                id=d["id"],
                ts=float(d["ts"]),
                target=d["target"],
                action=d["action"],
                content=d["content"],
                old_text=d.get("old_text", ""),
                reason=d["reason"],
                source=d["source"],
            ))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return props


def clear_proposals(repo_root: Path) -> None:
    """Truncate the proposals file (call after user review completes)."""
    path = _proposals_path(repo_root)
    if path.exists():
        path.write_text("", encoding="utf-8")


# ─── ProposalDistiller (S19) ──────────────────────────────────────────────────

def distill_proposals(repo_root: Path, *, limit_outcomes: int = 100) -> list[CurationProposal]:
    """Read queue + outcomes; generate and persist proposals; return them.

    Proposals are APPENDED to the proposals file (not replaced) so a run on
    an already-reviewed file won't duplicate. Caller is responsible for
    calling `clear_proposals` before asking the user to review.
    """
    import uuid

    proposals: list[CurationProposal] = []
    path = _proposals_path(repo_root)

    # 1. Queue-based proposals (v0 nudges → FAILURES or DECISIONS)
    for nudge in read_queue():
        hint = str(nudge.get("hint", ""))
        ts_val = float(str(nudge.get("ts", time.time())))
        if hint.startswith("pitfall:"):
            # strip "pitfall: " prefix for the entry content
            entry = hint[len("pitfall: "):].strip()
            prop = CurationProposal(
                id=uuid.uuid4().hex[:12],
                ts=ts_val,
                target="failures",
                action="add",
                content=entry,
                old_text="",
                reason=f"curation-queue nudge: {hint[:100]}",
                source="queue",
            )
            proposals.append(prop)
            _write_proposal(path, prop)
        elif hint.startswith("procedure:"):
            entry = hint[len("procedure: "):].strip()
            prop = CurationProposal(
                id=uuid.uuid4().hex[:12],
                ts=ts_val,
                target="decisions",
                action="add",
                content=f"Procedure that worked: {entry}",
                old_text="",
                reason=f"curation-queue nudge: {hint[:100]}",
                source="queue",
            )
            proposals.append(prop)
            _write_proposal(path, prop)

    # 2. Outcome-based proposals
    outcomes = read_outcomes(limit=limit_outcomes)
    fail_turns = [o for o in outcomes if o.tests_passed is False]
    pass_turns = [o for o in outcomes if o.tests_passed is True]
    correction_turns = [o for o in outcomes if o.user_correction]

    if fail_turns:
        # Surface the three most recent test-fail turns as FAILURES entries.
        for o in fail_turns[-3:]:
            entry = (
                f"Tests failed on purpose={o.purpose} model={o.model_id} — "
                f"prompt: {o.prompt_preview[:120]}"
            )
            prop = CurationProposal(
                id=uuid.uuid4().hex[:12],
                ts=o.ts,
                target="failures",
                action="add",
                content=entry,
                old_text="",
                reason=f"outcome: tests_passed=False on turn (purpose={o.purpose})",
                source="outcome",
            )
            proposals.append(prop)
            _write_proposal(path, prop)

    if pass_turns and len(pass_turns) >= 3:
        # If ≥3 consecutive passing turns with same purpose, add a DECISIONS note.
        recent_purposes = [o.purpose for o in pass_turns[-5:]]
        dominant = max(set(recent_purposes), key=recent_purposes.count)
        if recent_purposes.count(dominant) >= 3:
            entry = (
                f"Pattern: {dominant} turns consistently pass tests — "
                f"model routing to {pass_turns[-1].model_id} is working well for this repo."
            )
            prop = CurationProposal(
                id=uuid.uuid4().hex[:12],
                ts=time.time(),
                target="decisions",
                action="add",
                content=entry,
                old_text="",
                reason=f"outcome: {recent_purposes.count(dominant)}/5 recent {dominant} turns passed tests",
                source="outcome",
            )
            proposals.append(prop)
            _write_proposal(path, prop)

    if correction_turns:
        for o in correction_turns[-2:]:
            entry = (
                f"User correction detected after purpose={o.purpose} turn — "
                f"prompt: {o.prompt_preview[:120]}"
            )
            prop = CurationProposal(
                id=uuid.uuid4().hex[:12],
                ts=o.ts,
                target="failures",
                action="add",
                content=entry,
                old_text="",
                reason="outcome: user_correction=True",
                source="outcome",
            )
            proposals.append(prop)
            _write_proposal(path, prop)

    return proposals


# ─── apply_proposal() ─────────────────────────────────────────────────────────

def apply_proposal(repo_root: Path, proposal: CurationProposal) -> None:
    """Apply one accepted proposal to the relevant repo memory target.

    Raises ValueError if target is unknown or action is unsupported.
    """
    from tern.memory.repo_store import (
        RepoTarget,
        add_repo_entry,
        replace_repo_entry,
    )

    valid: tuple[RepoTarget, ...] = ("arch", "decisions", "failures", "reviewers")
    if proposal.target not in valid:
        raise ValueError(f"unknown target {proposal.target!r}")

    if proposal.action == "add":
        add_repo_entry(proposal.target, proposal.content, repo_root)
    elif proposal.action == "replace":
        if not proposal.old_text:
            raise ValueError("replace action requires non-empty old_text")
        replace_repo_entry(proposal.target, proposal.old_text, proposal.content, repo_root)
    else:
        raise ValueError(f"unsupported action {proposal.action!r}")


__all__ = [
    "CurationProposal",
    "OutcomeRecord",
    "ProposalTarget",
    "TurnSignal",
    "apply_proposal",
    "clear_proposals",
    "detect_commit_landed",
    "detect_tests_passed",
    "distill_proposals",
    "is_correction",
    "log_outcome",
    "maybe_queue_nudge",
    "read_outcomes",
    "read_proposals",
    "read_queue",
]
