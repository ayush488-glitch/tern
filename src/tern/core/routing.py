"""D1 cost router — picks a ProviderAdapter based on TurnPurpose.

This is the v0 policy:
  ARCH        -> Claude Opus 4
  CODE        -> Claude Sonnet 4 (default)
  LINT        -> Claude Haiku 4.5
  BOILERPLATE -> Amazon Nova Micro

Source of truth: token-cost-master skill + ADR-0004. USD pricing tables and
budget-aware fallbacks land in S10. For now the policy is a static map.

We construct adapters lazily (one per purpose, cached) so importing this
module does not eagerly init boto3 clients.
"""

from __future__ import annotations

from functools import cache

from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter
from tern.core.provider import ProviderAdapter
from tern.core.turn import TurnPurpose

# Bedrock model ids per ~/.hermes/skills/token-cost/token-cost-master/references.
# Claude 4 family on Bedrock requires the `us.` cross-region inference profile
# prefix; on-demand throughput is not supported for the bare model id.
_MODEL_FOR_PURPOSE: dict[TurnPurpose, str] = {
    TurnPurpose.ARCH: "us.anthropic.claude-opus-4-20250514-v1:0",
    TurnPurpose.CODE: "us.anthropic.claude-sonnet-4-20250514-v1:0",
    TurnPurpose.LINT: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    TurnPurpose.BOILERPLATE: "us.amazon.nova-micro-v1:0",
}


@cache
def _adapter_for(model_id: str) -> BedrockAnthropicAdapter:
    return BedrockAnthropicAdapter(model_id=model_id)


def select_adapter(purpose: TurnPurpose) -> ProviderAdapter:
    """Return the adapter responsible for this turn's purpose.

    Total over TurnPurpose. KeyError here means a new TurnPurpose got added
    without a routing entry — fail loud.
    """
    model_id = _MODEL_FOR_PURPOSE[purpose]
    return _adapter_for(model_id)


def default_router() -> ProviderAdapter:
    """No-purpose fallback. Goes to the code workhorse (Sonnet)."""
    return select_adapter(TurnPurpose.CODE)
