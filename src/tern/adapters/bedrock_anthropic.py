"""Bedrock-Anthropic adapter — first concrete ProviderAdapter (ADR-0004).

Translates Tern's vendor-neutral CanonicalMessage tuples to and from the
AWS Bedrock invocation of Anthropic Claude's Messages API. Both translation
functions are pure; the only side effect is `complete()`, which calls
boto3's bedrock-runtime client.

The hard parts pinned by tests:
  - system messages are LIFTED to a top-level `system` field (not in messages[])
  - tool_call -> tool_use, tool_result -> tool_result-under-user-role
  - ToolSpec is wrapped BARE: {name, description, input_schema} (no OpenAI
    `{type: "function", function: {...}}` wrapper)
  - cache_breakpoints attach `cache_control: {type: "ephemeral"}` to the
    last block of the message at each requested index
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import boto3

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Capabilities,
    Cost,
    ImageBlock,
    Metadata,
    ProviderResponse,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)

# Anthropic Messages API version Bedrock expects in the request body.
_ANTHROPIC_VERSION = "bedrock-2023-05-31"


# Streaming tuple shape: ("text", str) | ("tool_use_start", dict) |
# ("tool_args_delta", str) | ("done", ProviderResponse)
StreamEvent = tuple[str, Any]


class BedrockAnthropicAdapter:
    """ProviderAdapter for Anthropic Claude served via AWS Bedrock.

    Conforms structurally to tern.core.provider.ProviderAdapter (Protocol).
    Sibling, not subclass — see ADR-0004 §rejected-A.
    """

    name = "bedrock-anthropic"

    def __init__(
        self,
        *,
        model_id: str,
        region: str = "us-east-1",
        capabilities: Capabilities | None = None,
    ) -> None:
        self.model_id = model_id
        self.region = region
        self.capabilities = capabilities or Capabilities(
            tool_use=True,
            vision=True,
            supports_caching=True,
            max_input_tokens=200_000,
        )
        # Cache of the last assistant message returned by complete(). Used by
        # the CLI to print plain text after the event stream finishes. Reset
        # on each complete() call.
        self.last_response_message: CanonicalMessage | None = None

    # ---- to_wire (pure) ----------------------------------------------------

    @staticmethod
    def to_wire(
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        system_parts: list[str] = []
        wire_messages: list[dict[str, Any]] = []
        breakpoint_set = set(cache_breakpoints)

        for canonical_idx, msg in enumerate(messages):
            if msg.role == "system":
                system_parts.extend(_extract_text(msg))
                continue

            wire_role, wire_content = _map_message(msg)
            if canonical_idx in breakpoint_set and wire_content:
                wire_content[-1]["cache_control"] = {"type": "ephemeral"}
            wire_messages.append({"role": wire_role, "content": wire_content})

        body: dict[str, Any] = {
            "anthropic_version": _ANTHROPIC_VERSION,
            "messages": wire_messages,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if tools:
            body["tools"] = [_tool_spec_to_wire(t) for t in tools]
        return body

    # ---- from_wire (pure) --------------------------------------------------

    @staticmethod
    def from_wire(response: dict[str, Any]) -> ProviderResponse:
        blocks: list[Any] = []
        for raw in response.get("content", []):
            block_type = raw.get("type")
            if block_type == "text":
                blocks.append(TextBlock(text=raw.get("text", "")))
            elif block_type == "tool_use":
                blocks.append(
                    ToolCallBlock(
                        id=raw["id"],
                        name=raw["name"],
                        args=dict(raw.get("input", {})),
                    )
                )
            else:
                # unknown block kinds are dropped; future schema additions land
                # via SCHEMA_VERSION bump, not silent acceptance here.
                continue

        usage = response.get("usage", {}) or {}
        cost = Cost(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            usd_in=0.0,  # USD pricing lives in routing/config (ADR-0004 open Q)
            usd_out=0.0,
        )
        message = CanonicalMessage(
            role="assistant",
            content=tuple(blocks),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=0.0,
                model_id=response.get("model"),
                cost=cost,
                provenance="bedrock-anthropic",
            ),
        )
        return ProviderResponse(
            message=message,
            stop_reason=response.get("stop_reason", ""),
            cost=cost,
            raw_id=response.get("id", ""),
        )

    # ---- complete (side-effecting; boto3) ---------------------------------

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
        body["max_tokens"] = max_tokens
        body["temperature"] = temperature

        client = boto3.client("bedrock-runtime", region_name=self.region)
        result = client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        raw_bytes = result["body"].read()
        decoded = json.loads(raw_bytes.decode("utf-8"))
        response = self.from_wire(decoded)
        self.last_response_message = response.message
        return response

    # ---- stream (side-effecting; boto3 streaming) -------------------------

    async def stream(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> AsyncIterator[StreamEvent]:
        """Stream a turn. Yields:

            ("text", "...partial text...")          for each text delta
            ("tool_use_start", {id, name})          when a tool block starts
            ("tool_args_delta", "...partial json...")  partial input_json
            ("done", ProviderResponse)              once stream ends

        Anthropic-on-Bedrock streaming uses content_block_start /
        content_block_delta / content_block_stop / message_delta / message_stop
        events in a server-sent stream. We assemble blocks as they arrive,
        then synthesize a ProviderResponse for the loop.
        """
        body = self.to_wire(messages, tools, cache_breakpoints=cache_breakpoints)
        body["max_tokens"] = max_tokens
        body["temperature"] = temperature

        client = boto3.client("bedrock-runtime", region_name=self.region)
        result = client.invoke_model_with_response_stream(
            modelId=self.model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )

        # Block accumulators: index → (type, payload-in-progress).
        text_blocks: dict[int, list[str]] = {}
        tool_blocks: dict[int, dict[str, Any]] = {}  # {"id", "name", "args_json"}
        block_kinds: dict[int, str] = {}
        stop_reason = "end_turn"
        usage_in = 0
        usage_out = 0
        raw_id = ""
        model_seen = ""

        for ev in result["body"]:
            chunk = ev.get("chunk")
            if not chunk:
                continue
            payload = json.loads(chunk["bytes"].decode("utf-8"))
            t = payload.get("type")
            if t == "message_start":
                msg = payload.get("message", {}) or {}
                raw_id = msg.get("id", "")
                model_seen = msg.get("model", "")
                u = msg.get("usage", {}) or {}
                usage_in = int(u.get("input_tokens", 0))
                usage_out = int(u.get("output_tokens", 0))
            elif t == "content_block_start":
                idx = int(payload.get("index", 0))
                block = payload.get("content_block", {}) or {}
                kind = block.get("type", "")
                block_kinds[idx] = kind
                if kind == "text":
                    text_blocks[idx] = []
                elif kind == "tool_use":
                    tool_blocks[idx] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "args_json": "",
                    }
                    yield ("tool_use_start", {
                        "id": block["id"],
                        "name": block["name"],
                    })
            elif t == "content_block_delta":
                idx = int(payload.get("index", 0))
                delta = payload.get("delta", {}) or {}
                d_type = delta.get("type")
                if d_type == "text_delta":
                    chunk_text = delta.get("text", "")
                    text_blocks.setdefault(idx, []).append(chunk_text)
                    yield ("text", chunk_text)
                elif d_type == "input_json_delta":
                    partial = delta.get("partial_json", "")
                    tool_blocks.setdefault(
                        idx, {"id": "", "name": "", "args_json": ""}
                    )["args_json"] += partial
                    yield ("tool_args_delta", partial)
            elif t == "content_block_stop":
                # nothing to do; we built blocks incrementally
                pass
            elif t == "message_delta":
                d = payload.get("delta", {}) or {}
                if "stop_reason" in d:
                    stop_reason = d["stop_reason"] or stop_reason
                u = payload.get("usage", {}) or {}
                if "output_tokens" in u:
                    usage_out = int(u["output_tokens"])
            elif t == "message_stop":
                pass

        # Reassemble final canonical message in original block order.
        all_indices = sorted(set(text_blocks) | set(tool_blocks))
        final_blocks: list[Any] = []
        for idx in all_indices:
            if block_kinds.get(idx) == "text":
                final_blocks.append(TextBlock(text="".join(text_blocks[idx])))
            elif block_kinds.get(idx) == "tool_use":
                tb = tool_blocks[idx]
                try:
                    args = json.loads(tb["args_json"]) if tb["args_json"] else {}
                except json.JSONDecodeError:
                    args = {}
                final_blocks.append(
                    ToolCallBlock(id=tb["id"], name=tb["name"], args=args)
                )

        cost = Cost(
            input_tokens=usage_in,
            output_tokens=usage_out,
            usd_in=0.0,
            usd_out=0.0,
        )
        message = CanonicalMessage(
            role="assistant",
            content=tuple(final_blocks),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=0.0,
                model_id=model_seen or self.model_id,
                cost=cost,
                provenance="bedrock-anthropic",
            ),
        )
        response = ProviderResponse(
            message=message,
            stop_reason=stop_reason,
            cost=cost,
            raw_id=raw_id,
        )
        self.last_response_message = response.message
        yield ("done", response)


# ---------------------------------------------------------------------------
# helpers — small, named, single-purpose
# ---------------------------------------------------------------------------


def _extract_text(msg: CanonicalMessage) -> list[str]:
    return [b.text for b in msg.content if isinstance(b, TextBlock)]


def _map_message(msg: CanonicalMessage) -> tuple[str, list[dict[str, Any]]]:
    """Return (wire_role, wire_content_blocks).

    Anthropic packs tool results under a user-role message with tool_result
    blocks. So when our canonical role is 'tool', we emit role='user' and
    let the tool_result blocks ride inside.
    """
    if msg.role == "tool":
        return "user", [_tool_result_to_wire(b) for b in msg.content if isinstance(b, ToolResultBlock)]

    blocks: list[dict[str, Any]] = []
    for b in msg.content:
        if isinstance(b, TextBlock):
            blocks.append({"type": "text", "text": b.text})
        elif isinstance(b, ToolCallBlock):
            blocks.append(
                {
                    "type": "tool_use",
                    "id": b.id,
                    "name": b.name,
                    "input": dict(b.args),
                }
            )
        elif isinstance(b, ToolResultBlock):
            # Rare: tool_result inside an assistant message. Anthropic doesn't
            # accept this shape, but tests don't exercise it; we keep parity.
            blocks.append(_tool_result_to_wire(b))
        elif isinstance(b, ImageBlock):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": b.media_type,
                        "data": b.data_b64,
                    },
                }
            )
    return msg.role, blocks


def _tool_result_to_wire(b: ToolResultBlock) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": b.call_id,
        "content": b.content,
    }
    if not b.ok:
        out["is_error"] = True
    return out


def _tool_spec_to_wire(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.input_schema,
    }
