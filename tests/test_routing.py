"""Tests for D1 cost routing skeleton.

This pins the policy table. Per token-cost-master:
  arch / security  -> Opus
  default code     -> Sonnet
  lint / format    -> Haiku
  boilerplate      -> Nova Micro
"""

from __future__ import annotations

import pytest

from tern.core.routing import default_router, select_adapter
from tern.core.turn import TurnPurpose


@pytest.mark.parametrize(
    "purpose, expected_substr",
    [
        (TurnPurpose.ARCH, "opus"),
        (TurnPurpose.CODE, "sonnet"),
        (TurnPurpose.LINT, "haiku"),
        (TurnPurpose.BOILERPLATE, "nova-micro"),
    ],
)
def test_select_adapter_returns_expected_model_for_purpose(
    purpose: TurnPurpose, expected_substr: str
) -> None:
    adapter = select_adapter(purpose)
    assert expected_substr in adapter.model_id.lower()


def test_default_router_returns_code_purpose_adapter() -> None:
    """Unspecified routing must default to the code workhorse (Sonnet)."""
    adapter = default_router()
    assert "sonnet" in adapter.model_id.lower()


def test_router_returns_provider_adapter_protocol() -> None:
    from tern.core.provider import ProviderAdapter

    adapter = select_adapter(TurnPurpose.CODE)
    # runtime_checkable Protocol: structural conformance check
    assert isinstance(adapter, ProviderAdapter)


def test_all_purposes_have_a_route() -> None:
    """Selector must be total over TurnPurpose. No KeyError, no None."""
    for purpose in TurnPurpose:
        adapter = select_adapter(purpose)
        assert adapter is not None
        assert adapter.model_id  # non-empty
