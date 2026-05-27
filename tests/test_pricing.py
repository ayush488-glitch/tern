"""Tests for src/tern/core/pricing.py — coverage of known model ids + math."""
from __future__ import annotations

from tern.core.pricing import cost_for, known_models, pricing_for


def test_pricing_known_anthropic() -> None:
    p = pricing_for("us.anthropic.claude-sonnet-4-20250514-v1:0")
    assert p.usd_in_per_m == 3.0
    assert p.usd_out_per_m == 15.0


def test_pricing_unknown_returns_zero() -> None:
    p = pricing_for("never-existed/foo-1")
    assert p.usd_in_per_m == 0.0
    assert p.usd_out_per_m == 0.0


def test_cost_math_one_million_each() -> None:
    usd_in, usd_out = cost_for("gpt-5-mini", 1_000_000, 1_000_000)
    assert usd_in == 1.0
    assert usd_out == 4.0


def test_cost_math_partial() -> None:
    usd_in, usd_out = cost_for("us.amazon.nova-micro-v1:0", 500_000, 250_000)
    # Nova micro = 0.035 in / 0.14 out
    assert abs(usd_in - 0.0175) < 1e-9
    assert abs(usd_out - 0.035) < 1e-9


def test_cost_zero_tokens() -> None:
    usd_in, usd_out = cost_for("gpt-5", 0, 0)
    assert (usd_in, usd_out) == (0.0, 0.0)


def test_known_models_contains_each_family() -> None:
    ids = known_models()
    assert any("anthropic.claude" in m for m in ids)
    assert any("amazon.nova" in m for m in ids)
    assert any(m.startswith("gpt-") for m in ids)
