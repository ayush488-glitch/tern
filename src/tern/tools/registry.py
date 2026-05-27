"""Tool registry — the first of two permission gates (ADR-0003 §double-gate).

Filter at registry: tools the active mode forbids never reach the model's
tool list. `--safe` drops every destructive tool before the request even
goes out; `--yolo` keeps everything. The second gate (PermissionGate) runs
at call site, after the model picked a tool from whatever survived here.
"""

from __future__ import annotations

from collections.abc import Iterable

from tern.core.canonical import ToolSpec
from tern.tools.protocol import Tool, spec_for


class Registry:
    """Holds Tool instances by name. Mode-aware filtering.

    Construction is order-preserving so deterministic tests can assert on
    the model-visible tool list.
    """

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def visible_to_model(self, *, mode: str) -> list[Tool]:
        """First-gate filter. Returns the tools the model is even allowed to see.

        `safe`     — read-only only (drops anything `destructive`).
        `default`  — everything; second gate prompts at call site.
        `yolo`     — everything; second gate auto-approves.
        """
        if mode == "safe":
            return [t for t in self._tools.values() if not t.annotations.destructive]
        return list(self._tools.values())

    def specs(self, *, mode: str) -> tuple[ToolSpec, ...]:
        """Convenience: visible tools rendered as canonical ToolSpec for the wire."""
        return tuple(spec_for(t) for t in self.visible_to_model(mode=mode))

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools
