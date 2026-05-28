"""Heuristic-first turn-purpose classifier (ADR-0011 §1).

Two passes:
  1. Regex — zero cost. Matches keyword groups against the prompt.
     Returns on first hit.
  2. LLM fallback (Nova Micro) — fires only on a miss.
     One short prompt, ~$0.0001. Parses the one-word label out of the reply.

Returns (purpose, method) where method is "regex" | "llm" | "default".
"default" is returned when mode != "auto" (caller already chose a purpose).
"""
from __future__ import annotations

import re
from typing import Literal

from tern.core.turn import TurnPurpose

# ---------------------------------------------------------------------------
# Regex groups — ORDER MATTERS (first match wins)
# ---------------------------------------------------------------------------

_RULES: list[tuple[TurnPurpose, re.Pattern[str]]] = [
    (
        TurnPurpose.ARCH,
        re.compile(
            r"\b(architect|architecture|security|design doc|adr|adrs|"
            r"system design|race condition|threat model|audit)\b",
            re.IGNORECASE,
        ),
    ),
    (
        TurnPurpose.LINT,
        re.compile(
            r"\b(lint|format|rename|ruff|mypy|type.?check|"
            r"single.?line edit|whitespace|trailing comma)\b",
            re.IGNORECASE,
        ),
    ),
    (
        TurnPurpose.BOILERPLATE,
        re.compile(
            r"\b(boilerplate|scaffold|stub|skeleton|autocomplete|"
            r"generate tests?|__init__|empty file)\b",
            re.IGNORECASE,
        ),
    ),
    (
        TurnPurpose.CODE,
        re.compile(
            r"\b(implement|debug|fix|refactor|review|add|write|"
            r"create|update|extend|build)\b",
            re.IGNORECASE,
        ),
    ),
]

# ---------------------------------------------------------------------------
# LLM-fallback classifier prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a one-word classifier for a coding agent.
Given a user prompt, classify it into exactly one of: arch, code, lint, boilerplate.

arch        — architecture, system design, security review, ADR, race conditions
code        — implementation, debugging, review, refactor, feature work
lint        — lint/format/rename/type-check, single-line edits
boilerplate — scaffold, stub, skeleton, boilerplate, test generation

Reply with ONLY the label, no punctuation, no explanation.
"""

_PURPOSE_FROM_LABEL: dict[str, TurnPurpose] = {
    "arch": TurnPurpose.ARCH,
    "code": TurnPurpose.CODE,
    "lint": TurnPurpose.LINT,
    "boilerplate": TurnPurpose.BOILERPLATE,
}

Method = Literal["regex", "llm", "default"]


def _regex_classify(prompt: str) -> TurnPurpose | None:
    """Return TurnPurpose on first regex hit, or None on miss."""
    for purpose, pattern in _RULES:
        if pattern.search(prompt):
            return purpose
    return None


def _llm_classify(prompt: str) -> TurnPurpose:
    """Fire Nova Micro for a one-word label. Falls back to CODE on any error."""
    try:


        from tern.adapters.bedrock_nova import BedrockNovaAdapter
        from tern.core.canonical import SCHEMA_VERSION, CanonicalMessage, Metadata, TextBlock

        adapter = BedrockNovaAdapter(model_id="us.amazon.nova-micro-v1:0")
        import asyncio

        msgs: tuple[CanonicalMessage, ...] = (
            CanonicalMessage(
                role="system",
                content=(TextBlock(text=_SYSTEM_PROMPT),),
                metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="router"),
            ),
            CanonicalMessage(
                role="user",
                content=(TextBlock(text=prompt[:500]),),
                metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="router"),
            ),
        )

        async def _call() -> str:
            resp = await adapter.complete(msgs, tools=(), max_tokens=8, temperature=0.0)
            for blk in resp.message.content:
                if isinstance(blk, TextBlock):
                    return blk.text.strip().lower().split()[0]
            return "code"

        label = asyncio.run(_call())
        return _PURPOSE_FROM_LABEL.get(label, TurnPurpose.CODE)
    except Exception:
        return TurnPurpose.CODE


def classify(
    prompt: str,
    *,
    mode: str = "auto",
    llm_fallback: bool = True,
) -> tuple[TurnPurpose, Method]:
    """Classify a prompt into a TurnPurpose.

    Args:
        prompt: The raw user prompt text.
        mode: "auto" triggers classification; any other value returns
              (TurnPurpose.CODE, "default") immediately (used when the caller
              already pinned a purpose via --purpose flag).
        llm_fallback: If False, skip the Nova Micro call (useful for CI / yolo mode).

    Returns:
        (purpose, method) — method is "regex", "llm", or "default".
    """
    if mode != "auto":
        return TurnPurpose.CODE, "default"

    hit = _regex_classify(prompt)
    if hit is not None:
        return hit, "regex"

    if not llm_fallback:
        return TurnPurpose.CODE, "regex"  # safe fallback

    return _llm_classify(prompt), "llm"
