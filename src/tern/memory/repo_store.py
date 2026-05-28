"""Repo-scoped operational memory — Layer A of the moat plan (ADR-0011 §S17).

Storage layout inside the repo being edited:
    <repo_root>/.tern/memory/ARCH.md       — architecture decisions
    <repo_root>/.tern/memory/DECISIONS.md  — short-form ADRs
    <repo_root>/.tern/memory/FAILURES.md   — failure patterns + fixes
    <repo_root>/.tern/memory/REVIEWERS.md  — reviewer preferences

All four files use the same entry format as the global store (§-separated).
Writes are atomic. `find_repo_root` walks upward from cwd looking for .git or
.tern — whichever comes first makes that directory the repo root. Returns None
if neither marker is found (caller decides what to do).

Per ADR-0002: repo memory is INJECTED into the system prompt of the new turn.
It does not mutate the canonical message log.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Literal

RepoTarget = Literal["arch", "decisions", "failures", "reviewers"]

REPO_TARGETS: tuple[RepoTarget, ...] = ("arch", "decisions", "failures", "reviewers")
_FILENAME: dict[str, str] = {
    "arch": "ARCH.md",
    "decisions": "DECISIONS.md",
    "failures": "FAILURES.md",
    "reviewers": "REVIEWERS.md",
}

# Per-file character caps (advisory — same warning-only policy as global store)
_CAP: dict[str, int] = {
    "arch": 2000,
    "decisions": 2000,
    "failures": 2000,
    "reviewers": 1000,
}

_SEP = "§"


# ---------------------------------------------------------------------------
# repo detection
# ---------------------------------------------------------------------------


def find_repo_root(cwd: Path | None = None) -> Path | None:
    """Walk up from *cwd* looking for a .git or .tern marker directory.

    The first ancestor that contains either marker is the repo root.
    Returns None when neither is found (e.g. in /tmp scratch).
    """
    start = (cwd or Path.cwd()).resolve()
    current = start
    while True:
        if (current / ".git").exists() or (current / ".tern").exists():
            return current
        parent = current.parent
        if parent == current:
            # filesystem root — no marker found
            return None
        current = parent


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


def repo_memory_dir(repo_root: Path) -> Path:
    d = repo_root / ".tern" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_memory_path(repo_root: Path, target: str) -> Path:
    if target not in _FILENAME:
        raise ValueError(f"unknown repo memory target: {target!r}")
    return repo_memory_dir(repo_root) / _FILENAME[target]


# ---------------------------------------------------------------------------
# entry parse / serialize (same logic as global store)
# ---------------------------------------------------------------------------


def _split_entries(text: str) -> list[str]:
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
    if not entries:
        return ""
    return ("\n" + _SEP + "\n").join(e.strip("\n") for e in entries) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".repomem-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def load_repo_memory(target: str, repo_root: Path) -> tuple[tuple[str, ...], str]:
    """Load entries from one repo memory file.

    Returns (entries, raw_text). Empty tuple + '' when the file doesn't exist.
    """
    path = repo_memory_path(repo_root, target)
    raw = path.read_text("utf-8") if path.exists() else ""
    return tuple(_split_entries(raw)), raw


def add_repo_entry(target: str, content: str, repo_root: Path) -> tuple[str, ...]:
    """Append a new entry. Returns the post-write entries tuple."""
    content = content.strip()
    if not content:
        raise ValueError("repo memory entry must not be empty")
    entries, _ = load_repo_memory(target, repo_root)
    new_entries = [*entries, content]
    _atomic_write(repo_memory_path(repo_root, target), _join_entries(new_entries))
    return tuple(new_entries)


def _find_index(entries: tuple[str, ...], needle: str) -> int:
    if not needle.strip():
        raise ValueError("old_text must not be empty")
    n = needle.strip().lower()
    hits = [i for i, e in enumerate(entries) if n in e.lower()]
    if not hits:
        raise LookupError(f"no repo memory entry matches: {needle!r}")
    if len(hits) > 1:
        raise LookupError(
            f"old_text {needle!r} matches {len(hits)} entries; be more specific"
        )
    return hits[0]


def replace_repo_entry(
    target: str, old_text: str, content: str, repo_root: Path
) -> tuple[str, ...]:
    content = content.strip()
    if not content:
        raise ValueError("replacement content must not be empty")
    entries, _ = load_repo_memory(target, repo_root)
    lst = list(entries)
    lst[_find_index(entries, old_text)] = content
    _atomic_write(repo_memory_path(repo_root, target), _join_entries(lst))
    return tuple(lst)


def remove_repo_entry(
    target: str, old_text: str, repo_root: Path
) -> tuple[str, ...]:
    entries, _ = load_repo_memory(target, repo_root)
    lst = list(entries)
    lst.pop(_find_index(entries, old_text))
    _atomic_write(repo_memory_path(repo_root, target), _join_entries(lst))
    return tuple(lst)


# ---------------------------------------------------------------------------
# banner rendering
# ---------------------------------------------------------------------------


def render_repo_banner(repo_root: Path) -> str:
    """Render the composite REPO MEMORY banner for the system prompt.

    Returns '' when all four files are empty (fresh repo — no extra tokens).
    Banner order within the block: ARCH, DECISIONS, FAILURES, REVIEWERS.
    """
    sections: list[str] = []
    for key in REPO_TARGETS:
        entries, _ = load_repo_memory(key, repo_root)
        if not entries:
            continue
        title = f"## {key.upper()}"
        body = ("\n" + _SEP + "\n").join(e.strip("\n") for e in entries)
        sections.append(title + "\n" + body)

    if not sections:
        return ""

    header = (
        "══════════════════════════════════════════════\n"
        "REPO MEMORY (./.tern/memory)\n"
        "══════════════════════════════════════════════"
    )
    return header + "\n" + "\n\n".join(sections)


__all__ = [
    "REPO_TARGETS",
    "RepoTarget",
    "add_repo_entry",
    "find_repo_root",
    "load_repo_memory",
    "remove_repo_entry",
    "render_repo_banner",
    "replace_repo_entry",
    "repo_memory_dir",
    "repo_memory_path",
]
