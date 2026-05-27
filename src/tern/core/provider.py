"""Provider adapter contract.

Per ADR-0004 §rejected-A: adapters are SIBLING implementations, not subclasses
of a base. They share only this Protocol. Shared logic across Anthropic, OpenAI,
Bedrock, and litellm is approximately zero (different auth, different message
shapes, different streaming, different tool wrapping). A base class either ends
up empty or becomes a god-conditional. Protocol keeps the contract honest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from tern.core.canonical import (
    CanonicalMessage,
    Capabilities,
    ProviderResponse,
    ToolSpec,
)


@runtime_checkable
class ProviderAdapter(Protocol):
    """Anything that can turn canonical messages into a model response.

    Implementations live under src/tern/adapters/<vendor>.py. The agent core
    (M3) holds a reference of this Protocol type and never imports an adapter
    directly: this is what makes D1 (per-turn cost routing) and D3
    (replay/branch across providers) possible.
    """

    name: str
    model_id: str
    capabilities: Capabilities

    async def complete(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> ProviderResponse:
        """Run one turn against the underlying provider."""
        ...

    @staticmethod
    def to_wire(
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        """canonical -> provider wire format. Must be pure."""
        ...

    @staticmethod
    def from_wire(response: Any) -> ProviderResponse:
        """provider wire format -> canonical. Must be pure."""
        ...


# Optional streaming protocol — adapters that implement `stream()` enable
# token-by-token UI rendering. The loop calls hasattr(adapter, "stream")
# and falls back to `complete()` otherwise. Keeping streaming optional means
# fakes and offline adapters don't need to implement it.
#
# Tuple shape:
#   ("text", str)                 — partial assistant text
#   ("tool_use_start", dict)      — {id, name} when a tool block opens
#   ("tool_args_delta", str)      — partial tool input json
#   ("done", ProviderResponse)    — once stream ends; loop uses this
StreamEvent = tuple[str, Any]


@runtime_checkable
class StreamingProviderAdapter(Protocol):
    """Marker Protocol for adapters that support `stream()`."""

    def stream(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> AsyncIterator[StreamEvent]: ...
