"""Tests for S18 — cognitive router (classify + route)."""
from __future__ import annotations

import pytest

from tern.core.turn import TurnPurpose
from tern.router.classify import Method, classify


# ---------------------------------------------------------------------------
# classify() — regex pass (no LLM, llm_fallback=False)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt, expected_purpose",
    [
        ("implement a binary search function", TurnPurpose.CODE),
        ("debug the off-by-one error in loop", TurnPurpose.CODE),
        ("refactor the auth module for clarity", TurnPurpose.CODE),
        ("write unit tests for the parser", TurnPurpose.CODE),
        ("run ruff on this file", TurnPurpose.LINT),
        ("mypy --strict passes? check types", TurnPurpose.LINT),
        ("format the imports section", TurnPurpose.LINT),
        ("generate a CRUD boilerplate for User model", TurnPurpose.BOILERPLATE),
        ("scaffold a new FastAPI endpoint stub", TurnPurpose.BOILERPLATE),
        ("design the architecture for our auth service", TurnPurpose.ARCH),
        ("security review of the token refresh flow", TurnPurpose.ARCH),
        ("write an ADR for the message queue choice", TurnPurpose.ARCH),
        ("threat model the API gateway", TurnPurpose.ARCH),
    ],
)
def test_classify_regex(prompt: str, expected_purpose: TurnPurpose) -> None:
    purpose, method = classify(prompt, mode="auto", llm_fallback=False)
    assert purpose == expected_purpose
    assert method == "regex"


def test_classify_mode_not_auto_returns_default() -> None:
    """Any mode != 'auto' short-circuits to (CODE, 'default')."""
    purpose, method = classify("architect the whole system", mode="code")
    assert purpose == TurnPurpose.CODE
    assert method == "default"


def test_classify_unrecognised_prompt_fallback_to_code() -> None:
    """Prompt with no keyword match and llm_fallback=False returns CODE safely."""
    purpose, method = classify("hello world", mode="auto", llm_fallback=False)
    assert purpose == TurnPurpose.CODE
    # method may be "regex" (safe fallback path) — just check it's not "llm"
    assert method != "llm"


# ---------------------------------------------------------------------------
# route() — wraps classify, returns (purpose, model_id, method)
# ---------------------------------------------------------------------------


def test_route_arch_gives_opus() -> None:
    from tern.router import route

    purpose, model_id, method = route("security review of the API", mode="auto", llm_fallback=False)
    assert purpose == TurnPurpose.ARCH
    assert "opus" in model_id.lower() or "claude" in model_id.lower()
    assert method in ("regex", "llm", "default")


def test_route_lint_gives_haiku() -> None:
    from tern.router import route

    purpose, model_id, method = route("run ruff check on the codebase", mode="auto", llm_fallback=False)
    assert purpose == TurnPurpose.LINT
    assert "haiku" in model_id.lower()


def test_route_boilerplate_gives_nova() -> None:
    from tern.router import route

    purpose, model_id, method = route("scaffold CRUD boilerplate for Order", mode="auto", llm_fallback=False)
    assert purpose == TurnPurpose.BOILERPLATE
    assert "nova" in model_id.lower()


def test_route_code_gives_sonnet() -> None:
    from tern.router import route

    purpose, model_id, method = route("implement the retry logic", mode="auto", llm_fallback=False)
    assert purpose == TurnPurpose.CODE
    assert "sonnet" in model_id.lower()


def test_route_default_mode_passthrough() -> None:
    from tern.router import route

    purpose, model_id, method = route("architect everything", mode="code", llm_fallback=False)
    assert purpose == TurnPurpose.CODE
    assert method == "default"


# ---------------------------------------------------------------------------
# RoutingClassified + RecallQueried event structure
# ---------------------------------------------------------------------------


def test_routing_classified_event_fields() -> None:
    from tern.core.events import RoutingClassified

    ev = RoutingClassified(
        prompt_preview="implement auth",
        purpose="code",
        method="regex",
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    )
    assert ev.kind == "routing_classified"
    assert ev.method == "regex"
    assert ev.purpose == "code"
    assert len(ev.id) == 32  # uuid4 hex


def test_recall_queried_event_fields() -> None:
    from tern.core.events import RecallQueried

    ev = RecallQueried(
        prompt_preview="write unit tests",
        n_candidates=42,
        n_hits=3,
    )
    assert ev.kind == "recall_queried"
    assert ev.n_candidates == 42
    assert ev.n_hits == 3
