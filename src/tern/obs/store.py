"""S10 / D3 — content-addressed turn-object store + session refs.

Per ADR-0005 §Storage. Layout, rooted at ~/.tern/projects/<sanitized-cwd>/:

    objects/<sha[:2]>/<sha[2:]>     immutable turn-objects, content-addressed
    refs/sessions/<uuid>             current head turn-hash for a session
    refs/branches/<session>/<name>   named branches off a session
    sessions/<uuid>.jsonl            human-readable transcript (derived)

Turn-objects are the system of record. Refs and transcripts are derived; on
loss they rebuild from the object store. We never mutate an object once
written.

The hashing contract: stable JSON (sort_keys, tight separators) of asdict() →
sha256 → lowercase hex. content_hash(obj) IS the file name. Same shape as
git's blob storage; we steal git's data layout, not git itself (rejected
alternative C in ADR-0005).

I/O is synchronous. Writes are atomic (tempfile + os.replace). Reads tolerate
partial sessions (a session that crashed mid-write may have a refs entry
pointing at a hash whose object got fsynced — we never write the ref before
the object).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    ContentBlock,
    Cost,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from tern.obs.paths import project_dir

# ---------------------------------------------------------------------------
# Turn-object schema (ADR-0005 §Turn-object schema)
# ---------------------------------------------------------------------------

TurnRole = Literal["user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class TurnObject:
    """One immutable record in the conversation graph.

    `parent` is the only graph edge. None marks a session root. Editing a turn
    means creating a new TurnObject with the same parent and a new hash (see
    rewrite-and-continue in ADR-0005).
    """

    role: TurnRole
    content: tuple[ContentBlock, ...]
    parent: str | None = None
    model_id: str | None = None
    routing_purpose: str | None = None
    cost: Cost | None = None
    seed: int | None = None
    ts: int = 0
    schema_version: int = SCHEMA_VERSION
    # Optional pointers back into the operational data the recorder produced.
    # NOT part of the hash semantics' uniqueness — stored alongside.
    session_id: str | None = None
    turn_idx: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stable serialization + hash
# ---------------------------------------------------------------------------


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses, tuples, etc. to plain JSON values."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    return obj


def stable_json(obj: TurnObject) -> str:
    return json.dumps(_to_jsonable(obj), sort_keys=True, separators=(",", ":"))


def content_hash(obj: TurnObject) -> str:
    return hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Rehydration — the inverse of stable_json. Used by tern resume/replay.
# ---------------------------------------------------------------------------

_BLOCK_BY_KIND: dict[str, type] = {
    "text": TextBlock,
    "tool_call": ToolCallBlock,
    "tool_result": ToolResultBlock,
    "image": ImageBlock,
}


def _block_from_dict(d: dict[str, Any]) -> ContentBlock:
    kind = d["kind"]
    cls = _BLOCK_BY_KIND.get(kind)
    if cls is None:
        raise ValueError(f"unknown content block kind: {kind!r}")
    return cls(**d)  # type: ignore[no-any-return]


def _cost_from_dict(d: dict[str, Any] | None) -> Cost | None:
    if d is None:
        return None
    return Cost(**d)


def turn_from_dict(d: dict[str, Any]) -> TurnObject:
    return TurnObject(
        role=d["role"],
        content=tuple(_block_from_dict(b) for b in d.get("content", [])),
        parent=d.get("parent"),
        model_id=d.get("model_id"),
        routing_purpose=d.get("routing_purpose"),
        cost=_cost_from_dict(d.get("cost")),
        seed=d.get("seed"),
        ts=d.get("ts", 0),
        schema_version=d.get("schema_version", SCHEMA_VERSION),
        session_id=d.get("session_id"),
        turn_idx=d.get("turn_idx"),
        extra=d.get("extra", {}),
    )


# ---------------------------------------------------------------------------
# Path helpers — single source of truth for store layout
# ---------------------------------------------------------------------------


def _root(cwd: Path | None) -> Path:
    return project_dir(cwd)


def objects_dir(cwd: Path | None = None) -> Path:
    d = _root(cwd) / "objects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def object_path(sha: str, cwd: Path | None = None) -> Path:
    if len(sha) < 4:
        raise ValueError(f"hash too short: {sha!r}")
    return objects_dir(cwd) / sha[:2] / sha[2:]


def sessions_refs_dir(cwd: Path | None = None) -> Path:
    d = _root(cwd) / "refs" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_ref_path(session_id: str, cwd: Path | None = None) -> Path:
    return sessions_refs_dir(cwd) / session_id


def branches_refs_dir(session_id: str, cwd: Path | None = None) -> Path:
    d = _root(cwd) / "refs" / "branches" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def branch_ref_path(session_id: str, name: str, cwd: Path | None = None) -> Path:
    return branches_refs_dir(session_id, cwd=cwd) / name


def transcripts_dir(cwd: Path | None = None) -> Path:
    d = _root(cwd) / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcript_path(session_id: str, cwd: Path | None = None) -> Path:
    return transcripts_dir(cwd) / f"{session_id}.jsonl"


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Object store API
# ---------------------------------------------------------------------------


def write_object(obj: TurnObject, *, cwd: Path | None = None) -> str:
    """Hash, persist, return the hash. Idempotent — same content → same path."""
    sha = content_hash(obj)
    path = object_path(sha, cwd=cwd)
    if path.exists():
        return sha
    _atomic_write_text(path, stable_json(obj))
    return sha


def read_object(sha: str, *, cwd: Path | None = None) -> TurnObject:
    path = object_path(sha, cwd=cwd)
    if not path.exists():
        raise FileNotFoundError(f"no turn-object {sha} at {path}")
    return turn_from_dict(json.loads(path.read_text("utf-8")))


def has_object(sha: str, *, cwd: Path | None = None) -> bool:
    return object_path(sha, cwd=cwd).exists()


# ---------------------------------------------------------------------------
# Refs API
# ---------------------------------------------------------------------------


def update_session_head(session_id: str, sha: str, *, cwd: Path | None = None) -> None:
    _atomic_write_text(session_ref_path(session_id, cwd=cwd), sha + "\n")


def read_session_head(session_id: str, *, cwd: Path | None = None) -> str | None:
    p = session_ref_path(session_id, cwd=cwd)
    if not p.exists():
        return None
    return p.read_text("utf-8").strip() or None


def list_sessions(cwd: Path | None = None) -> list[tuple[str, str, float]]:
    """[(session_id, head_sha, mtime), ...] newest first."""
    d = sessions_refs_dir(cwd)
    out: list[tuple[str, str, float]] = []
    for p in d.iterdir():
        if not p.is_file():
            continue
        try:
            sha = p.read_text("utf-8").strip()
        except OSError:
            continue
        if sha:
            out.append((p.name, sha, p.stat().st_mtime))
    out.sort(key=lambda r: r[2], reverse=True)
    return out


def write_branch(
    session_id: str, name: str, sha: str, *, cwd: Path | None = None
) -> None:
    _atomic_write_text(branch_ref_path(session_id, name, cwd=cwd), sha + "\n")


def read_branch(
    session_id: str, name: str, *, cwd: Path | None = None
) -> str | None:
    p = branch_ref_path(session_id, name, cwd=cwd)
    if not p.exists():
        return None
    return p.read_text("utf-8").strip() or None


def list_branches(session_id: str, cwd: Path | None = None) -> list[tuple[str, str]]:
    d = branches_refs_dir(session_id, cwd=cwd)
    out: list[tuple[str, str]] = []
    for p in d.iterdir():
        if not p.is_file():
            continue
        sha = p.read_text("utf-8").strip()
        if sha:
            out.append((p.name, sha))
    out.sort(key=lambda r: r[0])
    return out


# ---------------------------------------------------------------------------
# Walk parents → chain (root → head)
# ---------------------------------------------------------------------------


def walk_chain(head_sha: str, *, cwd: Path | None = None) -> list[TurnObject]:
    """Walk parent links from `head_sha` back to root. Return root → head order."""
    chain: list[TurnObject] = []
    seen: set[str] = set()
    current: str | None = head_sha
    while current is not None:
        if current in seen:
            raise RuntimeError(f"cycle detected at {current}")
        seen.add(current)
        obj = read_object(current, cwd=cwd)
        chain.append(obj)
        current = obj.parent
    chain.reverse()
    return chain


def chain_to_messages(chain: list[TurnObject]) -> tuple[CanonicalMessage, ...]:
    """Project a chain of turn-objects back into the canonical message log
    that the loop will re-feed. Drops nothing; preserves role/content order."""
    from tern.core.canonical import Metadata

    out: list[CanonicalMessage] = []
    for o in chain:
        meta = Metadata(
            schema_version=o.schema_version,
            ts=float(o.ts) if o.ts else 0.0,
            model_id=o.model_id,
            cost=o.cost,
            seed=o.seed,
            provenance="store",
        )
        out.append(CanonicalMessage(role=o.role, content=o.content, metadata=meta))
    return tuple(out)


# ---------------------------------------------------------------------------
# Transcript writer — derived JSONL view (ADR-0005 §Transcript format)
# ---------------------------------------------------------------------------


def append_transcript(
    session_id: str,
    obj: TurnObject,
    sha: str,
    turn_idx: int,
    *,
    cwd: Path | None = None,
) -> None:
    """Append one line to sessions/<session_id>.jsonl. Best-effort; transcript
    is derived. If this write fails the object store still has truth."""
    path = transcript_path(session_id, cwd=cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "turn": turn_idx,
        "hash": sha,
        "parent": obj.parent,
        "role": obj.role,
        "content": [_to_jsonable(b) for b in obj.content],
        "model_id": obj.model_id,
        "routing_purpose": obj.routing_purpose,
        "cost": _to_jsonable(obj.cost) if obj.cost else None,
        "ts": obj.ts,
    }
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.write("\n")


# ---------------------------------------------------------------------------
# High-level helper: persist a CanonicalMessage as a TurnObject in the chain
# ---------------------------------------------------------------------------


def persist_message(
    msg: CanonicalMessage,
    *,
    session_id: str,
    turn_idx: int,
    parent: str | None,
    cwd: Path | None = None,
    routing_purpose: str | None = None,
) -> tuple[TurnObject, str]:
    """Write one canonical message into the store as a turn-object. Returns
    (object, hash). Caller is responsible for stitching the chain (passing
    the returned hash as the next message's parent and updating the session
    head when the turn finishes)."""
    if msg.role == "system":
        raise ValueError("system messages are prompts, not turn-objects; do not persist")
    role: TurnRole = msg.role  # type: ignore[assignment,unused-ignore]
    obj = TurnObject(
        role=role,
        content=tuple(msg.content),
        parent=parent,
        model_id=msg.metadata.model_id,
        routing_purpose=routing_purpose,
        cost=msg.metadata.cost,
        seed=msg.metadata.seed,
        ts=int(time.time() * 1e9),
        session_id=session_id,
        turn_idx=turn_idx,
    )
    sha = write_object(obj, cwd=cwd)
    append_transcript(session_id, obj, sha, turn_idx, cwd=cwd)
    return obj, sha


__all__ = [
    "TurnObject",
    "append_transcript",
    "branch_ref_path",
    "branches_refs_dir",
    "chain_to_messages",
    "content_hash",
    "has_object",
    "list_branches",
    "list_sessions",
    "object_path",
    "objects_dir",
    "persist_message",
    "read_branch",
    "read_object",
    "read_session_head",
    "session_ref_path",
    "sessions_refs_dir",
    "stable_json",
    "transcript_path",
    "turn_from_dict",
    "update_session_head",
    "walk_chain",
    "write_branch",
    "write_object",
]
