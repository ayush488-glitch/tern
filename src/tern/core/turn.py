"""Turn primitives — what one cycle of the agent loop knows about itself.

A Turn is a plan: which messages to send, which model purpose to route to,
which tools the model may call, how big the response can be, how many steps
the loop will tolerate before stopping.

Per ADR-0002 §runtime-shape, the agent core never holds mutable per-turn state
on `self`. Every turn is an explicit value passed through. The loop builds a
NEW Turn each step (with the rolling messages) rather than mutating in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from tern.core.canonical import CanonicalMessage
from tern.tools import PermissionGate, Registry


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
    # ---- M5 wiring (S9). Defaults preserve S8 call-sites that don't pass
    # tools or a permission gate.
    registry: Registry | None = None
    gate: PermissionGate | None = None
    mode: str = "default"
    repo_root: Path = field(default_factory=Path.cwd)
    max_steps: int = 10
