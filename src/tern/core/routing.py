"""D1 cost router — picks a ProviderAdapter based on TurnPurpose or explicit model_id.

Three model families supported as of S16:
  - Bedrock Anthropic (Claude 4 Opus/Sonnet/Haiku)
  - Bedrock Nova (Lite / Pro / Micro)
  - OpenAI direct (GPT-5 / GPT-5-mini / GPT-4o family)

Routing policy (TurnPurpose -> default model_id) lives in `_MODEL_FOR_PURPOSE`.
Override per-turn with `tern run --model <model_id>` or globally via
`tern config set default_model <model_id>`.

`adapter_for_model(model_id)` is the factory: it dispatches on the model_id
prefix to the right adapter family. New families = one new branch + one new
import. Per ADR-0004 §rejected-A: no shared base, no inheritance.

Pricing for the cost banner lives in `tern.core.pricing`.
"""

from __future__ import annotations

from functools import cache

from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter
from tern.adapters.bedrock_nova import BedrockNovaAdapter
from tern.adapters.openai_adapter import OpenAIAdapter
from tern.core.provider import ProviderAdapter
from tern.core.turn import TurnPurpose

# Default model per purpose. Sources:
#   - token-cost-master skill
#   - ADR-0004
# Claude 4 family on Bedrock requires the `us.` cross-region inference profile
# prefix; on-demand throughput is not supported for the bare model id.
_MODEL_FOR_PURPOSE: dict[TurnPurpose, str] = {
    TurnPurpose.ARCH: "us.anthropic.claude-opus-4-20250514-v1:0",
    TurnPurpose.CODE: "us.anthropic.claude-sonnet-4-20250514-v1:0",
    TurnPurpose.LINT: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    TurnPurpose.BOILERPLATE: "us.amazon.nova-micro-v1:0",
}


def _is_bedrock_anthropic(model_id: str) -> bool:
    return "anthropic.claude" in model_id


def _is_bedrock_nova(model_id: str) -> bool:
    return "amazon.nova" in model_id


def _is_openai(model_id: str) -> bool:
    return model_id.startswith(("gpt-", "openai/", "o1", "o3"))


@cache
def adapter_for_model(model_id: str) -> ProviderAdapter:
    """Build (or reuse) an adapter for `model_id`.

    Dispatch is by string prefix — see ADR-0004. Raises ValueError if the id
    matches no known family; this is intentional, we want loud failures over
    silent wrong-routing.
    """
    if _is_bedrock_anthropic(model_id):
        return BedrockAnthropicAdapter(model_id=model_id)
    if _is_bedrock_nova(model_id):
        return BedrockNovaAdapter(model_id=model_id)
    if _is_openai(model_id):
        return OpenAIAdapter(model_id=model_id)
    raise ValueError(
        f"unknown model_id family: {model_id!r}. "
        f"Expected a Bedrock Anthropic (us.anthropic.claude-...), "
        f"Bedrock Nova (us.amazon.nova-...), or OpenAI (gpt-...) id."
    )


# Back-compat: tests and S9-S15 code used `_adapter_for(model_id)`.
_adapter_for = adapter_for_model


def select_adapter(purpose: TurnPurpose) -> ProviderAdapter:
    """Return the adapter for this turn's purpose.

    Total over TurnPurpose. KeyError here means a new TurnPurpose got added
    without a routing entry — fail loud.
    """
    return adapter_for_model(_MODEL_FOR_PURPOSE[purpose])


def default_router() -> ProviderAdapter:
    """No-purpose fallback. Goes to the code workhorse."""
    return select_adapter(TurnPurpose.CODE)


def model_for_purpose(purpose: TurnPurpose) -> str:
    """Public lookup, used by `tern config` and `tern models`."""
    return _MODEL_FOR_PURPOSE[purpose]
