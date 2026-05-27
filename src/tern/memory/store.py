"""Memory file I/O — atomic, separator-aware, cap-warning.

Storage:
    ~/.tern/memory/MEMORY.md    procedural notes
    ~/.tern/memory/USER.md      user profile

Both files are entry-separated by a single line `§`. Empty file = zero entries.
Writes are atomic (temp file + rename) so a crashed agent never leaves a
half-written memory blob.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tern.obs.paths import tern_home

Target = Literal["memory", "user"]

# Cap shapes mirror Hermes contract. They are warnings only — the tool surfaces
# the over-cap state to the agent so it can curate, but writes still succeed.
MEMORY_CAP = 2200
USER_CAP = 1375

_SEP = "§"


def _memory_dir() -> Path:
    d = tern_home() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_path() -> Path:
    return _memory_dir() / "MEMORY.md"


def user_path() -> Path:
    return _memory_dir() / "USER.md"


def _path_for(target: Target) -> Path:
    if target == "memory":
        return memory_path()
    if target == "user":
        return user_path()
    raise ValueError(f"unknown memory target: {target!r}")


def _cap_for(target: Target) -> int:
    return MEMORY_CAP if target == "memory" else USER_CAP


# ---------------------------------------------------------------------------
# parse / serialize
# ---------------------------------------------------------------------------


def _split_entries(text: str) -> list[str]:
    """Parse the on-disk format into a list of entry strings.

    Entries are separated by a line whose stripped content is exactly `§`.
    Whitespace inside an entry is preserved; leading/trailing blank lines on
    each entry are trimmed so round-tripping stays stable.
    """
    if not text.strip():
        return []
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == _SEP:
            joined = "\n".join(buf).strip("\n")
            if joined.strip():
                out.append(joined)
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip("\n")
    if tail.strip():
        out.append(tail)
    return out


def _join_entries(entries: list[str]) -> str:
    """Inverse of _split_entries. Entries joined by `\\n§\\n`. Empty list → ''.

    A trailing newline keeps the file POSIX-clean.
    """
    if not entries:
        return ""
    return ("\n" + _SEP + "\n").join(e.strip("\n") for e in entries) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".memory-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        # best-effort cleanup; never mask the original error
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# load / mutate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryFile:
    """Snapshot of one memory file."""

    target: Target
    entries: tuple[str, ...]
    text: str
    cap: int

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def over_cap(self) -> bool:
        return self.char_count > self.cap


def load_memory(target: Target) -> MemoryFile:
    p = _path_for(target)
    raw = p.read_text("utf-8") if p.exists() else ""
    entries = _split_entries(raw)
    return MemoryFile(
        target=target,
        entries=tuple(entries),
        text=raw,
        cap=_cap_for(target),
    )


def add_entry(target: Target, content: str) -> MemoryFile:
    """Append a new entry. Returns the post-state snapshot."""
    content = content.strip()
    if not content:
        raise ValueError("memory entry must not be empty")
    snap = load_memory(target)
    new_entries = [*snap.entries, content]
    new_text = _join_entries(new_entries)
    _atomic_write(_path_for(target), new_text)
    return MemoryFile(
        target=target,
        entries=tuple(new_entries),
        text=new_text,
        cap=snap.cap,
    )


def _find_index(entries: list[str], needle: str) -> int:
    """Return the index of the unique entry containing `needle` (substring,
    case-insensitive). Raise LookupError on zero or multiple matches.
    """
    if not needle.strip():
        raise ValueError("old_text must not be empty")
    n = needle.strip().lower()
    hits = [i for i, e in enumerate(entries) if n in e.lower()]
    if not hits:
        raise LookupError(f"no memory entry matches: {needle!r}")
    if len(hits) > 1:
        raise LookupError(
            f"old_text {needle!r} matches {len(hits)} entries; be more specific"
        )
    return hits[0]


def replace_entry(target: Target, old_text: str, content: str) -> MemoryFile:
    content = content.strip()
    if not content:
        raise ValueError("replacement content must not be empty")
    snap = load_memory(target)
    entries = list(snap.entries)
    idx = _find_index(entries, old_text)
    entries[idx] = content
    new_text = _join_entries(entries)
    _atomic_write(_path_for(target), new_text)
    return MemoryFile(
        target=target,
        entries=tuple(entries),
        text=new_text,
        cap=snap.cap,
    )


def remove_entry(target: Target, old_text: str) -> MemoryFile:
    snap = load_memory(target)
    entries = list(snap.entries)
    idx = _find_index(entries, old_text)
    entries.pop(idx)
    new_text = _join_entries(entries)
    _atomic_write(_path_for(target), new_text)
    return MemoryFile(
        target=target,
        entries=tuple(entries),
        text=new_text,
        cap=snap.cap,
    )


# ---------------------------------------------------------------------------
# system-prompt rendering
# ---------------------------------------------------------------------------


def render_banner(memfile: MemoryFile) -> str:
    """Render the banner the system prompt sees.

    Empty memory → empty string (no banner). This keeps a fresh-machine run
    from spending tokens on a placeholder.
    """
    if not memfile.entries:
        return ""
    title = "MEMORY (your personal notes)" if memfile.target == "memory" else "USER PROFILE (who the user is)"
    pct = round(memfile.char_count / memfile.cap * 100) if memfile.cap else 0
    over = "  ⚠ OVER CAP — consider curating" if memfile.over_cap else ""
    header = (
        "══════════════════════════════════════════════\n"
        f"{title} [{pct}% — {memfile.char_count}/{memfile.cap} chars]{over}\n"
        "══════════════════════════════════════════════"
    )
    body_parts: list[str] = []
    for i, entry in enumerate(memfile.entries):
        if i > 0:
            body_parts.append(_SEP)
        body_parts.append(entry)
    return header + "\n" + "\n".join(body_parts)


def render_all_banners() -> str:
    """Compose both banners, MEMORY then USER, separated by a blank line.

    Returns '' if both files are empty.
    """
    parts = [
        b for b in (
            render_banner(load_memory("memory")),
            render_banner(load_memory("user")),
        ) if b
    ]
    return "\n\n".join(parts)
