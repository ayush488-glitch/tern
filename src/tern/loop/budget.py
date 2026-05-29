"""Session + per-turn cost budget enforcement (S21 / ADR-0012 §6).

Config keys (stored in ~/.tern/config.json):
  budget.session   — float USD, soft limit per session (warn + ask to continue)
  budget.turn      — float USD, soft limit per individual LLM call

Hard limit = 2x soft limit. At hard limit, refuse the call and exit cleanly.

Usage in loop.py::

    budget = BudgetTracker.from_config()
    ...
    check = budget.check_turn(estimated_cost)
    if check == BudgetStatus.HARD_EXCEEDED:
        raise BudgetExceeded("turn hard limit reached")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BudgetStatus(Enum):
    OK = "ok"
    SOFT_WARN = "soft_warn"    # warn user, ask to continue
    HARD_EXCEEDED = "hard_exceeded"  # refuse, exit cleanly


class BudgetExceeded(RuntimeError):
    """Raised when a hard budget limit is hit."""


@dataclass
class BudgetTracker:
    """Track accumulated cost against session and per-turn budgets.

    All amounts in USD.
    """

    session_limit: float | None = None   # None = unlimited
    turn_limit: float | None = None      # None = unlimited
    _session_spent: float = field(default=0.0, init=False)

    @classmethod
    def from_config(cls, home: Path | None = None) -> BudgetTracker:
        """Load budget limits from ~/.tern/config.json."""
        from tern.core.config import _load

        data = _load(home)

        def _f(key: str) -> float | None:
            val = data.get(key)
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        return cls(
            session_limit=_f("budget.session"),
            turn_limit=_f("budget.turn"),
        )

    def record(self, cost_usd: float) -> None:
        """Record a completed LLM call cost."""
        self._session_spent += cost_usd

    @property
    def session_spent(self) -> float:
        return self._session_spent

    def check_turn(self, estimated_cost: float) -> BudgetStatus:
        """Check if a new turn call would exceed per-turn or session budgets.

        Call this BEFORE the LLM call. Pass estimated_cost (e.g. from pricing
        or previous-turn average). If the estimate is unknown, pass 0.0 and
        let post-call record() do the accounting.
        """
        if self.turn_limit is not None:
            hard = self.turn_limit * 2
            if estimated_cost >= hard:
                return BudgetStatus.HARD_EXCEEDED
            if estimated_cost >= self.turn_limit:
                return BudgetStatus.SOFT_WARN

        if self.session_limit is not None:
            projected = self._session_spent + estimated_cost
            hard = self.session_limit * 2
            if projected >= hard:
                return BudgetStatus.HARD_EXCEEDED
            if projected >= self.session_limit:
                return BudgetStatus.SOFT_WARN

        return BudgetStatus.OK

    def check_session(self) -> BudgetStatus:
        """Check session total against session budget (post-turn accounting)."""
        if self.session_limit is None:
            return BudgetStatus.OK
        hard = self.session_limit * 2
        if self._session_spent >= hard:
            return BudgetStatus.HARD_EXCEEDED
        if self._session_spent >= self.session_limit:
            return BudgetStatus.SOFT_WARN
        return BudgetStatus.OK


_VALID_BUDGET_KEYS = frozenset({"budget.session", "budget.turn"})


def validate_budget_key(key: str) -> None:
    """Raise ValueError if key is not a known budget config key."""
    if key not in _VALID_BUDGET_KEYS:
        raise ValueError(
            f"unknown budget key: {key!r}. valid: {sorted(_VALID_BUDGET_KEYS)}"
        )


__all__ = [
    "BudgetExceeded",
    "BudgetStatus",
    "BudgetTracker",
    "validate_budget_key",
]
