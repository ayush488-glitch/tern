"""route() — wraps classify() + adapter selection (ADR-0011 §1)."""
from __future__ import annotations

from tern.core.routing import model_for_purpose
from tern.core.turn import TurnPurpose
from tern.router.classify import Method, classify


def route(
    prompt: str,
    *,
    mode: str = "auto",
    llm_fallback: bool = True,
) -> tuple[TurnPurpose, str, Method]:
    """Classify the prompt and return (purpose, model_id, method).

    Callers use this to both pick the adapter AND emit a RoutingClassified span.

    Returns:
        purpose   — TurnPurpose
        model_id  — string model id (feeds adapter_for_model)
        method    — "regex" | "llm" | "default"
    """
    purpose, method = classify(prompt, mode=mode, llm_fallback=llm_fallback)
    model_id = model_for_purpose(purpose)
    return purpose, model_id, method
