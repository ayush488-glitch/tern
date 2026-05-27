"""S12 / D4 — note store.

Notes are free-form lines the agent (or a tool call) appends mid-turn. They
sit alongside the turn-object graph: turns are the system of record for what
was said; notes are the system of record for what the agent decided was
worth remembering. The HTML artifact (notes.html) merges both.

Storage layout (ADR-0007):

    <project_dir>/notes/<session_id>.jsonl

JSONL is append-only. Each line: {ts, turn_idx, kind, text, tags?}.
Kind is "note" (free-form) for now; reserved values let us add structure
later (e.g. "decision", "todo") without breaking existing files.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from tern.obs.paths import project_dir

NoteKind = Literal["note"]


@dataclass(frozen=True, slots=True)
class Note:
    """One row in the notes store."""

    text: str
    turn_idx: int
    kind: NoteKind = "note"
    ts: float = 0.0
    tags: tuple[str, ...] = field(default_factory=tuple)


def notes_path(session_id: str, *, cwd: Path | None = None) -> Path:
    d = project_dir(cwd) / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.jsonl"


def append_note(
    session_id: str,
    text: str,
    *,
    turn_idx: int,
    tags: tuple[str, ...] = (),
    cwd: Path | None = None,
    ts: float | None = None,
) -> Note:
    """Append one note row; return the persisted Note."""
    note = Note(
        text=text,
        turn_idx=turn_idx,
        kind="note",
        ts=ts if ts is not None else time.time(),
        tags=tags,
    )
    p = notes_path(session_id, cwd=cwd)
    line = json.dumps(asdict(note), sort_keys=True, ensure_ascii=False)
    # Append is naturally atomic on POSIX for short writes; we open with O_APPEND.
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return note


def read_notes(session_id: str, *, cwd: Path | None = None) -> tuple[Note, ...]:
    p = notes_path(session_id, cwd=cwd)
    if not p.exists():
        return ()
    out: list[Note] = []
    for raw in p.read_text("utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue  # tolerate partial trailing line
        out.append(
            Note(
                text=str(d.get("text", "")),
                turn_idx=int(d.get("turn_idx", 0)),
                kind="note",
                ts=float(d.get("ts", 0.0)),
                tags=tuple(d.get("tags") or ()),
            )
        )
    return tuple(out)


def truncate_notes(session_id: str, *, cwd: Path | None = None) -> None:
    """Replace with empty file (test helper / manual reset)."""
    p = notes_path(session_id, cwd=cwd)
    fd, tmp = tempfile.mkstemp(prefix=".notes-", dir=str(p.parent))
    os.close(fd)
    os.replace(tmp, p)


__all__ = [
    "Note",
    "NoteKind",
    "append_note",
    "notes_path",
    "read_notes",
    "truncate_notes",
]
