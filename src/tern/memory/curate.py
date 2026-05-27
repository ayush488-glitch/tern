"""Self-curation v0 — append-on-success hint queue.

Gated on env var `TERN_AUTO_CURATE=1`. When enabled, end-of-session emits a
one-line nudge into `~/.tern/memory/curation_queue.jsonl` whenever a
heuristic suggests there's a fact worth remembering. The agent picks these
up at the start of the next session and decides whether to upgrade them
into actual MEMORY.md / USER.md entries via the `memory` tool.

The bar for v0 is intentionally low: we don't auto-write to MEMORY.md (too
easy to corrupt the file with junk). We just leave breadcrumbs.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from tern.obs.paths import tern_home


def _enabled() -> bool:
    return os.environ.get("TERN_AUTO_CURATE", "").strip() in ("1", "true", "yes")


def _queue_path() -> Path:
    d = tern_home() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "curation_queue.jsonl"


@dataclass(frozen=True, slots=True)
class TurnSignal:
    """Coarse summary of one turn for the curator's heuristics."""

    session_id: str
    tool_names: tuple[str, ...]
    tool_calls: int
    error_count: int
    user_text: str


def _heuristic_hint(signal: TurnSignal) -> str | None:
    """Decide whether this turn earned a curation nudge.

    Heuristics, in priority order:
      1. user said "remember" / "don't do that again" / "save this" → strong signal
      2. ≥5 tool calls and zero errors → procedure that worked, worth a skill
      3. an error + recovery → pitfall worth logging
      4. otherwise → no nudge
    """
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
    out: list[dict[str, object]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


__all__ = ["TurnSignal", "maybe_queue_nudge", "read_queue"]
