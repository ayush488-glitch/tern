"""Per-model USD pricing — populated from token-cost-master references (mid-2026).

Single source of truth for $/1M in/out. The router and adapters both read from
here so a price change is one edit. Unknown model_ids return zero cost (silent;
we don't want a missing entry to break a turn — just shows as $0.0000 in the
banner). Add new entries as adapters land.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pricing:
    usd_in_per_m: float   # USD per 1M input tokens
    usd_out_per_m: float  # USD per 1M output tokens


# Mid-2026 list pricing. Bedrock and direct-vendor prices match within rounding.
_TABLE: dict[str, Pricing] = {
    # Anthropic via Bedrock (us. cross-region inference profile)
    "us.anthropic.claude-opus-4-20250514-v1:0":     Pricing(15.0, 75.0),
    "us.anthropic.claude-sonnet-4-20250514-v1:0":   Pricing(3.0, 15.0),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0":  Pricing(1.0, 5.0),
    # Amazon Nova (Bedrock)
    "us.amazon.nova-micro-v1:0":  Pricing(0.035, 0.14),
    "us.amazon.nova-lite-v1:0":   Pricing(0.06, 0.24),
    "us.amazon.nova-pro-v1:0":    Pricing(0.80, 3.20),
    # OpenAI direct
    "gpt-5":      Pricing(10.0, 40.0),
    "gpt-5-mini": Pricing(1.0, 4.0),
    "gpt-4o":     Pricing(2.50, 10.0),
    "gpt-4o-mini": Pricing(0.15, 0.60),
}


def pricing_for(model_id: str) -> Pricing:
    """Lookup, returning zero-cost stub for unknown model_ids."""
    return _TABLE.get(model_id, Pricing(0.0, 0.0))


def cost_for(model_id: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
    """Return (usd_in, usd_out) for this turn. Pure."""
    p = pricing_for(model_id)
    usd_in = (input_tokens / 1_000_000.0) * p.usd_in_per_m
    usd_out = (output_tokens / 1_000_000.0) * p.usd_out_per_m
    return usd_in, usd_out


def known_models() -> tuple[str, ...]:
    """Stable tuple of known model_ids — for `tern models` listing."""
    return tuple(_TABLE.keys())
