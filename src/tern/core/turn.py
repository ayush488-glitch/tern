"""Turn primitives — what one cycle of the agent loop knows about itself.

A Turn is a plan: which messages to send, which model purpose to route to,
how big the response can be. The loop (M1) consumes a Turn and yields events.

Per ADR-0002 §runtime-shape, the agent core never holds mutable per-turn state
on `self`. Every turn is an explicit value passed through.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tern.core.canonical import CanonicalMessage


class TurnPurpose(Enum):
    """Routing tag. Mirrors token-cost-master's decision tree.

    ARCH        architecture, security review, system design
    CODE        implementation, debug, review, refactor (default)
    LINT        lint, format, rename, single-line edit
    BOILERPLATE boilerplate, autocomplete, scaffold
    """

    ARCH = "arch"
    CODE = "code"
    LINT = "lint"
    BOILERPLATE = "boilerplate"


@dataclass(frozen=True, slots=True)
class Turn:
    id: str
    session_id: str
    idx: int
    purpose: TurnPurpose
    messages: tuple[CanonicalMessage, ...]
    max_tokens: int = 1024
    temperature: float = 0.0
