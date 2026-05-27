"""Span tree — derived view over a TurnEvent stream.

An event stream is a flat sequence; humans want a tree. The recorder pairs
opener+closer events into spans, nests via parent_id, and aggregates cost.

A `Span` is closed (has both endpoints) or open (only the opener seen).
Closed spans have a duration; open spans don't (they may be in-flight, or the
session may have aborted before close).

Tree shape:
    TurnStarted (span)
      ├─ LLMRequested→LLMResponded (span)
      ├─ ToolCalled→ToolReturned (span)
      │    └─ ApprovalRequested→ApprovalGranted (nested span)
      └─ TurnCompleted

All four pair-classes derive from the SAME Span shape — recorder doesn't
special-case. New pairs added later (e.g. NetworkRequested) need no recorder
changes, only a new entry in events._OPENERS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tern.core.events import (
    LLMRequested,
    LLMResponded,
    ToolCalled,
    ToolReturned,
    TurnEvent,
    TurnStarted,
)


@dataclass(slots=True)
class Span:
    """One opener+closer pair, with optional nested children.

    Spans are mutable during recording (children appended, closer set later)
    but conceptually frozen once `closer` is filled in. Recorder seals on
    close; renderers treat as read-only.
    """
    id: str
    parent_id: str | None
    kind: str  # opener kind, e.g. "llm_requested"
    opener: TurnEvent
    closer: TurnEvent | None = None
    children: list[Span] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_closed(self) -> bool:
        return self.closer is not None

    @property
    def duration_ns(self) -> int | None:
        if self.closer is None:
            return None
        return self.closer.ts - self.opener.ts

    @property
    def label(self) -> str:
        """Human label for tree rendering. Pair-specific summaries."""
        op = self.opener
        if isinstance(op, TurnStarted):
            return f"turn {op.turn_idx} (session {op.session_id[:8]})"
        if isinstance(op, LLMRequested):
            cost = ""
            if isinstance(self.closer, LLMResponded):
                cost = f" · {self.closer.tokens_in}+{self.closer.tokens_out}tok · ${self.closer.cost_usd:.4f}"
            return f"llm {op.model_id} [{op.routing_purpose}]{cost}"
        if isinstance(op, ToolCalled):
            ok = ""
            if isinstance(self.closer, ToolReturned):
                ok = " ✓" if self.closer.ok else f" ✗ {self.closer.error or ''}"
            return f"tool {op.tool_name}{ok}"
        return self.kind

    def total_cost_usd(self) -> float:
        """Recursively sum cost. LLMResponded events carry the dollars; everyone
        else contributes via children."""
        total = 0.0
        if isinstance(self.closer, LLMResponded):
            total += self.closer.cost_usd
        for child in self.children:
            total += child.total_cost_usd()
        return total
