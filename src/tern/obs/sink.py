"""NDJSON sink — append-only event log.

One line per event. Stable JSON (sort_keys=True, separators=(",",":")) so
hashes are reproducible if/when ADR-0005's content-addressing wants to hash
the sink later. Append-only; we never rewrite.

The sink is the system of record for spans. The Span tree (obs.span) is a
derived view; you can rebuild it from this file alone.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tern.core.events import TurnEvent, event_to_dict
from tern.obs.paths import spans_path
from tern.obs.redact import Redactor


class NDJSONSpanSink:
    """Append events to a per-session ndjson file. Synchronous fsync-on-write
    is intentional — we'd rather lose throughput than lose the trail."""

    def __init__(
        self,
        session_id: str,
        *,
        cwd: Path | None = None,
        redact: bool = True,
    ) -> None:
        self.path: Path = spans_path(session_id, cwd=cwd)
        self.session_id: str = session_id
        # Per-session Redactor: same secret → same placeholder across all events
        # in this session, so the trail stays correlatable without leaking.
        self._redactor: Redactor | None = Redactor() if redact else None

    def write(self, ev: TurnEvent) -> None:
        payload = event_to_dict(ev)
        if self._redactor is not None:
            payload = self._redactor.scrub_obj(payload)
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")

    @staticmethod
    def read_all(path: Path) -> Iterator[dict[str, Any]]:
        """Read raw event dicts. Use rebuild_events() to materialize back into
        TurnEvent instances."""
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)
