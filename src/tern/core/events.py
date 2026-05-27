"""Turn events — the vocabulary every consumer reads.

Specified by wiki/decisions/adr-0002-runtime-shape.md §"A turn is an async
generator". One stream, many consumers (TUI, span recorder, persister, tests).

Every event is a frozen dataclass. Every event carries a stable `id` (uuid4
hex), a `ts` (ns since epoch), a `parent_id` (the open event this one closes
or nests under, if any), and an event-specific payload.

Open events come in pairs:
    LLMRequested   → LLMResponded
    ToolCalled     → ToolReturned
    ApprovalRequested → ApprovalGranted | ApprovalDenied

Singleton events (no pair):
    ReflectionTriggered, UserAborted, TurnCompleted, TurnStarted

The span recorder (M11) closes pairs and produces span trees from this stream;
the loop (M1) yields it; the TUI (M2) renders it. None of those modules need
to know each other.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


def _gen_id() -> str:
    return uuid.uuid4().hex


def _now_ns() -> int:
    return time.time_ns()


@dataclass(frozen=True, slots=True)
class _EventBase:
    id: str = field(default_factory=_gen_id)
    ts: int = field(default_factory=_now_ns)
    parent_id: str | None = None


# ─── lifecycle ────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TurnStarted(_EventBase):
    session_id: str = ""
    turn_idx: int = 0
    kind: Literal["turn_started"] = "turn_started"


@dataclass(frozen=True, slots=True)
class TurnCompleted(_EventBase):
    reason: Literal[
        "done",
        "max_steps",
        "user_abort",
        "permission_denied",
        "provider_error",
    ] = "done"
    kind: Literal["turn_completed"] = "turn_completed"


@dataclass(frozen=True, slots=True)
class UserAborted(_EventBase):
    kind: Literal["user_aborted"] = "user_aborted"


# ─── llm pair ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class LLMRequested(_EventBase):
    model_id: str = ""
    routing_purpose: str = "default"
    n_messages: int = 0
    n_tools: int = 0
    kind: Literal["llm_requested"] = "llm_requested"


@dataclass(frozen=True, slots=True)
class LLMResponded(_EventBase):
    model_id: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    stop_reason: str = "end_turn"
    kind: Literal["llm_responded"] = "llm_responded"


# ─── tool pair ────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ToolCalled(_EventBase):
    tool_name: str = ""
    call_id: str = ""
    args_preview: str = ""  # truncated repr; full args live in canonical log
    kind: Literal["tool_called"] = "tool_called"


@dataclass(frozen=True, slots=True)
class ToolReturned(_EventBase):
    tool_name: str = ""
    call_id: str = ""
    ok: bool = True
    bytes_out: int = 0
    error: str | None = None
    kind: Literal["tool_returned"] = "tool_returned"


# ─── approval pair ────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ApprovalRequested(_EventBase):
    tool_name: str = ""
    call_id: str = ""
    reason: str = ""
    kind: Literal["approval_requested"] = "approval_requested"


@dataclass(frozen=True, slots=True)
class ApprovalGranted(_EventBase):
    tool_name: str = ""
    call_id: str = ""
    kind: Literal["approval_granted"] = "approval_granted"


@dataclass(frozen=True, slots=True)
class ApprovalDenied(_EventBase):
    tool_name: str = ""
    call_id: str = ""
    reason: str = ""
    kind: Literal["approval_denied"] = "approval_denied"


# ─── reflection ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ReflectionTriggered(_EventBase):
    depth: int = 1
    cause: str = ""
    kind: Literal["reflection_triggered"] = "reflection_triggered"


# ─── union & helpers ──────────────────────────────────────────────────────────

TurnEvent = (
    TurnStarted
    | TurnCompleted
    | UserAborted
    | LLMRequested
    | LLMResponded
    | ToolCalled
    | ToolReturned
    | ApprovalRequested
    | ApprovalGranted
    | ApprovalDenied
    | ReflectionTriggered
)


_OPENERS: dict[str, str] = {
    "llm_responded": "llm_requested",
    "tool_returned": "tool_called",
    "approval_granted": "approval_requested",
    "approval_denied": "approval_requested",
}


def opener_kind_for(closer_kind: str) -> str | None:
    """Return the opener-event kind that this closer event closes, if any."""
    return _OPENERS.get(closer_kind)


def event_to_dict(ev: TurnEvent) -> dict[str, Any]:
    """Stable dict representation for NDJSON sink. Field order doesn't matter
    because we sort_keys on dump; what matters is that every field is JSON-safe."""
    from dataclasses import asdict
    return asdict(ev)
