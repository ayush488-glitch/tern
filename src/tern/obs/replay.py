"""Rebuild events + recorder state from an NDJSON sink file.

Lets `tern spans <session>` reconstruct the span tree without re-running the
turn. The dispatch table here is the inverse of events.event_to_dict.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tern.core import events as ev
from tern.obs.recorder import SpanRecorder
from tern.obs.sink import NDJSONSpanSink

_KIND_TO_CLASS: dict[str, type] = {
    "turn_started": ev.TurnStarted,
    "turn_completed": ev.TurnCompleted,
    "user_aborted": ev.UserAborted,
    "llm_requested": ev.LLMRequested,
    "llm_responded": ev.LLMResponded,
    "tool_called": ev.ToolCalled,
    "tool_returned": ev.ToolReturned,
    "approval_requested": ev.ApprovalRequested,
    "approval_granted": ev.ApprovalGranted,
    "approval_denied": ev.ApprovalDenied,
    "reflection_triggered": ev.ReflectionTriggered,
}


def event_from_dict(raw: dict[str, Any]) -> ev.TurnEvent:
    kind = raw["kind"]
    cls = _KIND_TO_CLASS.get(kind)
    if cls is None:
        raise ValueError(f"unknown event kind: {kind!r}")
    return cls(**raw)  # type: ignore[no-any-return]


def replay_to_recorder(path: Path) -> SpanRecorder:
    rec = SpanRecorder()
    for raw in NDJSONSpanSink.read_all(path):
        rec.consume(event_from_dict(raw))
    return rec
