"""Tests for the routing factory — model_id -> adapter dispatch."""
from __future__ import annotations

import pytest

from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter
from tern.adapters.bedrock_nova import BedrockNovaAdapter
from tern.adapters.openai_adapter import OpenAIAdapter
from tern.core.routing import (
    adapter_for_model,
    default_router,
    model_for_purpose,
    select_adapter,
)
from tern.core.turn import TurnPurpose


def test_anthropic_id_routes_to_anthropic_adapter() -> None:
    a = adapter_for_model("us.anthropic.claude-sonnet-4-20250514-v1:0")
    assert isinstance(a, BedrockAnthropicAdapter)


def test_nova_id_routes_to_nova_adapter() -> None:
    a = adapter_for_model("us.amazon.nova-lite-v1:0")
    assert isinstance(a, BedrockNovaAdapter)


def test_openai_id_routes_to_openai_adapter() -> None:
    a = adapter_for_model("gpt-5-mini")
    assert isinstance(a, OpenAIAdapter)


def test_unknown_family_raises() -> None:
    with pytest.raises(ValueError, match="unknown model_id family"):
        adapter_for_model("totally-fake-model")


def test_select_adapter_uses_purpose_default() -> None:
    a = select_adapter(TurnPurpose.CODE)
    assert isinstance(a, BedrockAnthropicAdapter)
    assert "sonnet" in a.model_id


def test_default_router_is_code_purpose() -> None:
    assert default_router().model_id == model_for_purpose(TurnPurpose.CODE)


def test_factory_caches_per_model_id() -> None:
    a1 = adapter_for_model("us.amazon.nova-pro-v1:0")
    a2 = adapter_for_model("us.amazon.nova-pro-v1:0")
    assert a1 is a2  # @cache should return same instance


def test_purpose_map_total() -> None:
    # All TurnPurpose values must be routable
    for p in TurnPurpose:
        assert isinstance(model_for_purpose(p), str)
