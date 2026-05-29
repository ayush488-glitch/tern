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
class LLMTextDelta(_EventBase):
    """Streaming text fragment from the LLM. Emitted between LLMRequested and
    LLMResponded when the adapter supports streaming. UI consumers append the
    `text` field directly; recorders may ignore (final text lives in the
    canonical message attached to LLMResponded's parent turn)."""
    text: str = ""
    kind: Literal["llm_text_delta"] = "llm_text_delta"


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


# ─── routing + recall (S18) ───────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class RoutingClassified(_EventBase):
    """Fired once per turn before the LLM call when the auto-router fires.

    `method` is one of "regex" (heuristic pass hit), "llm" (Nova Micro fallback),
    or "default" (auto-router was not enabled, purpose came from --purpose flag).
    """
    prompt_preview: str = ""     # first 120 chars of user prompt
    purpose: str = ""            # TurnPurpose.value e.g. "code"
    method: str = "default"      # "regex" | "llm" | "default"
    model_id: str = ""           # model chosen after routing
    kind: Literal["routing_classified"] = "routing_classified"


@dataclass(frozen=True, slots=True)
class RecallQueried(_EventBase):
    """Fired once per turn when KNN recall runs (even if 0 hits returned)."""
    prompt_preview: str = ""     # first 120 chars of user prompt
    n_candidates: int = 0        # vectors in the index
    n_hits: int = 0              # results returned (top-k)
    kind: Literal["recall_queried"] = "recall_queried"


# ─── outcome spans (S19) ──────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class OutcomeSpan(_EventBase):
    """Fired at the end of a turn to record its ground-truth outcome.

    This is the training signal for the S19 curator's Bayesian priors.

    Fields:
        tests_passed    — True/False if we detected a pytest/test run in the turn;
                          None if no test run was detected.
        commit_landed   — True if `git commit` succeeded in the turn; None if not run.
        user_correction — True if the user's *next* prompt looks like a correction
                          (e.g. "no, actually...", "that's wrong", "undo"). Set
                          retroactively by the prior-turn recorder; False by default
                          (no look-ahead at emit time).
        purpose         — TurnPurpose.value string e.g. "code".
        model_id        — model used for this turn.
        tool_names      — sorted tuple of tool names called.
        error_count     — number of ToolReturned events with ok=False.
        prompt_preview  — first 120 chars of user prompt.
    """
    tests_passed: bool | None = None
    commit_landed: bool | None = None
    user_correction: bool = False
    purpose: str = ""
    model_id: str = ""
    tool_names: tuple[str, ...] = ()
    error_count: int = 0
    prompt_preview: str = ""
    kind: Literal["outcome_span"] = "outcome_span"


@dataclass(frozen=True, slots=True)
class SOLookupCompleted(_EventBase):
    """Fired after a StackOverflow lookup triggered by error_count >= 1.

    Carries the query used and how many hits were returned.
    The actual hits are injected into the next turn's system prompt
    via build_so_banner(); they do not live in the event.
    """
    query: str = ""
    n_hits: int = 0
    error_in_turn: str = ""   # first 120 chars of the error that triggered the lookup
    kind: Literal["so_lookup_completed"] = "so_lookup_completed"


@dataclass(frozen=True, slots=True)
class DiffPreviewEvent(_EventBase):
    """Emitted before a destructive write applies (S21 / ADR-0012 §5)."""

    path: str = ""
    diff: str = ""
    changed_lines: int = 0
    auto_applied: bool = False
    kind: Literal["diff_preview"] = "diff_preview"


# ─── union & helpers ──────────────────────────────────────────────────────────

TurnEvent = (
    TurnStarted
    | TurnCompleted
    | UserAborted
    | LLMRequested
    | LLMTextDelta
    | LLMResponded
    | ToolCalled
    | ToolReturned
    | ApprovalRequested
    | ApprovalGranted
    | ApprovalDenied
    | ReflectionTriggered
    | RoutingClassified
    | RecallQueried
    | OutcomeSpan
    | SOLookupCompleted
    | DiffPreviewEvent
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
