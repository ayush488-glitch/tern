"""Offline test doubles. Sibling adapters that pretend to be a provider."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Capabilities,
    Cost,
    Metadata,
    ProviderResponse,
    TextBlock,
    ToolSpec,
)


class FakeAdapter:
    """Conforms to ProviderAdapter Protocol. Records calls; returns a canned
    assistant message. No network."""

    name = "fake"

    def __init__(self, *, reply: str = "fake reply", model_id: str = "fake-model") -> None:
        self.model_id = model_id
        self.capabilities = Capabilities(tool_use=False, vision=False)
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> ProviderResponse:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        cost = Cost(input_tokens=7, output_tokens=3, usd_in=0.0, usd_out=0.0)
        msg = CanonicalMessage(
            role="assistant",
            content=(TextBlock(text=self._reply),),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=0.0,
                model_id=self.model_id,
                cost=cost,
                provenance="fake",
            ),
        )
        return ProviderResponse(
            message=msg, stop_reason="end_turn", cost=cost, raw_id="fake-id"
        )

    @staticmethod
    def to_wire(
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        return {"messages": [m.role for m in messages]}

    @staticmethod
    def from_wire(response: Any) -> ProviderResponse:
        # Not exercised in tests that use FakeAdapter; satisfies the Protocol.
        msg = CanonicalMessage(
            role="assistant",
            content=(TextBlock(text=str(response)),),
            metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="fake"),
        )
        cost = Cost(0, 0, 0.0, 0.0)
        return ProviderResponse(message=msg, stop_reason="end_turn", cost=cost, raw_id="")


def relabel_model(adapter: FakeAdapter, new_id: str) -> FakeAdapter:
    """Helper for tests that want a different model_id without rebuilding."""
    new = FakeAdapter(reply=adapter._reply, model_id=new_id)
    new.calls = adapter.calls
    return new


class FakeStreamingAdapter(FakeAdapter):
    """FakeAdapter + `stream()` that yields the reply char-by-char then 'done'."""

    async def stream(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> Any:
        self.calls.append(
            {"messages": messages, "tools": tools, "max_tokens": max_tokens,
             "temperature": temperature, "streamed": True}
        )
        for ch in self._reply:
            yield ("text", ch)
        cost = Cost(input_tokens=7, output_tokens=3, usd_in=0.0, usd_out=0.0)
        msg = CanonicalMessage(
            role="assistant",
            content=(TextBlock(text=self._reply),),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION, ts=0.0,
                model_id=self.model_id, cost=cost, provenance="fake",
            ),
        )
        yield ("done", ProviderResponse(
            message=msg, stop_reason="end_turn", cost=cost, raw_id="fake-id"
        ))


__all__ = ["FakeAdapter", "FakeStreamingAdapter", "relabel_model", "replace"]
