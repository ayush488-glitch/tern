"""Persist SO lookup hits between tern run invocations (S20).

Hits are written to ~/.tern/memory/so_hits.json after each lookup.
The next run reads them, injects the banner, then clears the file
so stale SO results don't linger past one turn.

File format: JSON array of SOHit dicts (plain, no compression).
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from tern.lookup.search import SOHit


def _hits_path() -> Path:
    tern_home = Path(os.environ.get("TERN_HOME", "~/.tern")).expanduser()
    mem = tern_home / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return mem / "so_hits.json"


def save_so_hits(hits: list[SOHit]) -> None:
    """Atomically persist hits list to disk. Overwrites any previous hits."""
    path = _hits_path()
    payload = [
        {
            "title": h.title,
            "link": h.link,
            "answer_id": h.answer_id,
            "score": h.score,
            "is_answered": h.is_answered,
            "answer_preview": h.answer_preview,
            "tags": list(h.tags),
        }
        for h in hits
    ]
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        os.close(fd)
        Path(tmp).write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def load_and_clear_so_hits() -> list[SOHit]:
    """Read persisted SO hits and delete the file.

    Returns empty list if no hits file exists.
    Call once at the start of each `tern run` turn to consume the hits
    produced by the previous turn's SO lookup.
    """
    path = _hits_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:
        return []
    finally:
        with contextlib.suppress(OSError):
            path.unlink()
    hits: list[SOHit] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        hits.append(SOHit(
            title=str(item.get("title", "")),
            link=str(item.get("link", "")),
            answer_id=int(item.get("answer_id", 0)),
            score=int(item.get("score", 0)),
            is_answered=bool(item.get("is_answered", False)),
            answer_preview=str(item.get("answer_preview", "")),
            tags=tuple(str(t) for t in item.get("tags", [])),
        ))
    return hits
