"""Content-addressed read cache for read_file (S21 / ADR-0012 §4).

Cache key: (absolute_path, mtime_ns, size_bytes).
On hit: return {cached: true, turn_idx, sha256} + the stored content.
On miss: store and return fresh.
Invalidated when mtime or size changes — never serves stale content.

Session-scoped: one ReadCache instance per tern run session.
Never persisted to disk; lives in memory only.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple


class _CacheKey(NamedTuple):
    path: str        # absolute path str
    mtime_ns: int    # Path.stat().st_mtime_ns
    size: int        # Path.stat().st_size


@dataclass
class _CacheEntry:
    sha256: str
    content: str       # numbered-lines body (same shape read_file returns)
    turn_idx: int      # which turn first read this
    total_lines: int


@dataclass
class ReadCache:
    """Session-scoped content-addressed cache for read_file results.

    Thread-safe for concurrent async use (single-threaded asyncio event loop).
    """

    _store: dict[_CacheKey, _CacheEntry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def _key(self, path: Path) -> _CacheKey | None:
        """Return the cache key for *path*, or None if stat fails."""
        try:
            st = path.stat()
        except OSError:
            return None
        return _CacheKey(str(path), st.st_mtime_ns, st.st_size)

    def get(self, path: Path) -> _CacheEntry | None:
        """Return cached entry if valid, None on miss or stat error."""
        key = self._key(path)
        if key is None:
            return None
        entry = self._store.get(key)
        if entry is not None:
            self.hits += 1
            return entry
        self.misses += 1
        return None

    def put(self, path: Path, content: str, turn_idx: int, total_lines: int) -> str:
        """Store *content* for *path* (current on-disk stat). Returns sha256."""
        key = self._key(path)
        sha = hashlib.sha256(content.encode()).hexdigest()
        if key is not None:
            self._store[key] = _CacheEntry(
                sha256=sha,
                content=content,
                turn_idx=turn_idx,
                total_lines=total_lines,
            )
        return sha

    @property
    def size(self) -> int:
        return len(self._store)


# Module-level singleton — replaced per session by cli.py injecting a fresh
# ReadCache into ToolContext. Tests can create their own instances.
_SESSION_CACHE: ReadCache | None = None


def get_session_cache() -> ReadCache:
    """Return (or lazily create) the process-level session cache."""
    global _SESSION_CACHE
    if _SESSION_CACHE is None:
        _SESSION_CACHE = ReadCache()
    return _SESSION_CACHE


def reset_session_cache() -> None:
    """Call at the start of each new session to clear stale entries."""
    global _SESSION_CACHE
    _SESSION_CACHE = ReadCache()


__all__ = ["ReadCache", "_CacheEntry", "get_session_cache", "reset_session_cache"]
