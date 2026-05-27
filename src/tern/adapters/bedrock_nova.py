"""ProviderAdapter for Amazon Nova (Lite/Pro/Micro) via AWS Bedrock InvokeModel.

Sibling to BedrockAnthropicAdapter — different wire format (Nova has its own
'messages' shape and 'toolConfig' / 'toolSpec' wrapping). Per ADR-0004 §rejected-A,
no shared base class.

Nova wire shape (request):
  {
    "messages": [{"role": "user", "content": [{"text": "..."}]}],
    "system":   [{"text": "..."}],
    "inferenceConfig": {"maxTokens": ..., "temperature": ...},
    "toolConfig": {"tools": [{"toolSpec": {"name", "description", "inputSchema": {"json": {...}}}}]}
  }

Response:
  {
    "output": {"message": {"content": [{"text": "..."}, {"toolUse": {...}}]}},
    "stopReason": "...",
    "usage": {"inputTokens": N, "outputTokens": N}
  }
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import boto3
from botocore.exceptions import ClientError

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Capabilities,
    Cost,
    Metadata,
    ProviderResponse,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)
from tern.core.pricing import cost_for

_RETRYABLE_CODES = {"ThrottlingException", "ServiceUnavailable", "InternalServerError"}
_MAX_RETRIES = 4


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in _RETRYABLE_CODES
    return False


async def _sleep_with_jitter(attempt: int) -> None:
    base = 0.5 * (2 ** attempt)
    await asyncio.sleep(base + random.random() * 0.25)


class BedrockNovaAdapter:
    """ProviderAdapter for Amazon Nova family on Bedrock.

    Sibling, not subclass.
    """

    name = "bedrock-nova"

    def __init__(
        self,
        *,
        model_id: str,
        region: str = "us-east-1",
        capabilities: Capabilities | None = None,
    ) -> None:
        self.model_id = model_id
        self.region = region
        # Nova Lite/Pro have vision; Micro is text-only. Conservative default.
        self.capabilities = capabilities or Capabilities(
            tool_use=True,
            vision="micro" not in model_id,
            supports_caching=False,
            max_input_tokens=300_000,
        )
        self.last_response_message: CanonicalMessage | None = None

    # ---- to_wire ----------------------------------------------------------

    @staticmethod
    def to_wire(
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        system_parts: list[str] = []
        wire_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        system_parts.append(b.text)
                continue

            content_blocks: list[dict[str, Any]] = []
            wire_role = msg.role
            for b in msg.content:
                if isinstance(b, TextBlock):
                    if b.text:
                        content_blocks.append({"text": b.text})
                elif isinstance(b, ToolCallBlock):
                    content_blocks.append({
                        "toolUse": {
                            "toolUseId": b.id,
                            "name": b.name,
                            "input": dict(b.args),
                        }
                    })
                elif isinstance(b, ToolResultBlock):
                    # Nova: tool results live in user-role messages
                    wire_role = "user"
                    payload: list[dict[str, Any]] = [{"text": b.content or ""}]
                    content_blocks.append({
                        "toolResult": {
                            "toolUseId": b.call_id,
                            "content": payload,
                            **({"status": "error"} if not b.ok else {}),
                        }
                    })
                # ImageBlock support deferred to S17 vision wiring.

            if content_blocks:
                wire_messages.append({"role": wire_role, "content": content_blocks})

        body: dict[str, Any] = {"messages": wire_messages}
        if system_parts:
            body["system"] = [{"text": "\n\n".join(system_parts)}]
        if tools:
            body["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.input_schema},
                        }
                    }
                    for t in tools
                ]
            }
        return body

    # ---- from_wire --------------------------------------------------------

    @staticmethod
    def from_wire(response: dict[str, Any]) -> ProviderResponse:
        blocks: list[Any] = []
        output = response.get("output", {}) or {}
        msg = output.get("message", {}) or {}
        for raw in msg.get("content", []) or []:
            if "text" in raw:
                blocks.append(TextBlock(text=raw["text"]))
            elif "toolUse" in raw:
                tu = raw["toolUse"]
                blocks.append(
                    ToolCallBlock(
                        id=tu.get("toolUseId", ""),
                        name=tu.get("name", ""),
                        args=dict(tu.get("input", {})),
                    )
                )

        usage = response.get("usage", {}) or {}
        in_tok = int(usage.get("inputTokens", 0))
        out_tok = int(usage.get("outputTokens", 0))
        # Pricing fold-in happens in routing layer; keep zero here for parity
        # with bedrock_anthropic's local stub. Cost banner uses pricing.cost_for.
        cost = Cost(input_tokens=in_tok, output_tokens=out_tok, usd_in=0.0, usd_out=0.0)
        message = CanonicalMessage(
            role="assistant",
            content=tuple(blocks),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=0.0,
                model_id=response.get("model"),
                cost=cost,
                provenance="bedrock-nova",
            ),
        )
        return ProviderResponse(
            message=message,
            stop_reason=response.get("stopReason", ""),
            cost=cost,
            raw_id=response.get("id", ""),
        )

    # ---- complete ---------------------------------------------------------

    async def complete(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> ProviderResponse:
        body = self.to_wire(messages, tools, cache_breakpoints=cache_breakpoints)
        body["inferenceConfig"] = {"maxTokens": max_tokens, "temperature": temperature}

        client = boto3.client("bedrock-runtime", region_name=self.region)
        last_exc: BaseException | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                result = client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(body).encode("utf-8"),
                    accept="application/json",
                    contentType="application/json",
                )
                break
            except ClientError as exc:
                last_exc = exc
                if attempt >= _MAX_RETRIES or not _is_retryable(exc):
                    raise
                await _sleep_with_jitter(attempt)
        else:  # pragma: no cover
            assert last_exc is not None
            raise last_exc

        raw_bytes = result["body"].read()
        decoded = json.loads(raw_bytes.decode("utf-8"))
        response = self.from_wire(decoded)
        # Fold pricing in
        usd_in, usd_out = cost_for(self.model_id, response.cost.input_tokens, response.cost.output_tokens)
        priced_cost = Cost(
            input_tokens=response.cost.input_tokens,
            output_tokens=response.cost.output_tokens,
            usd_in=usd_in,
            usd_out=usd_out,
        )
        priced_msg = CanonicalMessage(
            role=response.message.role,
            content=response.message.content,
            metadata=Metadata(
                schema_version=response.message.metadata.schema_version,
                ts=response.message.metadata.ts,
                model_id=self.model_id,
                cost=priced_cost,
                seed=response.message.metadata.seed,
                provenance=response.message.metadata.provenance,
            ),
        )
        priced = ProviderResponse(
            message=priced_msg,
            stop_reason=response.stop_reason,
            cost=priced_cost,
            raw_id=response.raw_id,
        )
        self.last_response_message = priced_msg
        return priced
