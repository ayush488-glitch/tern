"""ProviderAdapter for OpenAI (GPT-5, GPT-5-mini, GPT-4o family) via REST.

Sibling to BedrockAnthropicAdapter / BedrockNovaAdapter. Uses httpx (already a
boto3 transitive dep) so no new requirement. Endpoint: POST /v1/chat/completions.

API key resolution: env OPENAI_API_KEY first, then ~/.tern/secrets.json,
then prompt on first use (only in TTY).

Wire format (Chat Completions):
  request:
    {"model": "...", "messages": [{"role": "...", "content": "..."}],
     "tools": [{"type": "function", "function": {"name", "description", "parameters"}}],
     "max_tokens": N, "temperature": F}
  response:
    {"choices": [{"message": {"role": "assistant", "content": "...", "tool_calls": [...]},
                  "finish_reason": "..."}],
     "usage": {"prompt_tokens": N, "completion_tokens": N}}
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx

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
from tern.core.secrets import get_secret

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_MAX_RETRIES = 4
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def _sleep_with_jitter(attempt: int) -> None:
    base = 0.5 * (2 ** attempt)
    await asyncio.sleep(base + random.random() * 0.25)


class OpenAIAdapter:
    """ProviderAdapter for OpenAI Chat Completions.

    Sibling, not subclass. Per-instance api_key is resolved lazily on first
    complete() call so constructing the adapter never blocks on stdin during
    static routing.
    """

    name = "openai"

    def __init__(
        self,
        *,
        model_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: str | None = None,
        capabilities: Capabilities | None = None,
    ) -> None:
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self._api_key_override = api_key
        # GPT-5 and 4o have vision; mini variants vary, take a safe stance.
        self.capabilities = capabilities or Capabilities(
            tool_use=True,
            vision="mini" not in model_id,
            supports_caching=False,
            max_input_tokens=128_000,
        )
        self.last_response_message: CanonicalMessage | None = None

    def _resolve_key(self) -> str:
        if self._api_key_override:
            return self._api_key_override
        key = get_secret(
            "OPENAI_API_KEY",
            interactive=True,
            prompt="OPENAI_API_KEY not set. Paste it now (saved to ~/.tern/secrets.json, chmod 600): ",
        )
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Either export it, run "
                "`tern config set OPENAI_API_KEY <value>`, or pass --model "
                "with a Bedrock model id."
            )
        return key

    # ---- to_wire ---------------------------------------------------------

    @staticmethod
    def to_wire(
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, Any]] = []
        for msg in messages:
            text_parts: list[str] = []
            tool_calls_out: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []  # become role=tool messages

            for b in msg.content:
                if isinstance(b, TextBlock):
                    if b.text:
                        text_parts.append(b.text)
                elif isinstance(b, ToolCallBlock):
                    tool_calls_out.append({
                        "id": b.id,
                        "type": "function",
                        "function": {
                            "name": b.name,
                            "arguments": json.dumps(b.args),
                        },
                    })
                elif isinstance(b, ToolResultBlock):
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": b.call_id,
                        "content": b.content or "",
                    })

            entry: dict[str, Any] = {"role": msg.role}
            if text_parts:
                entry["content"] = "\n\n".join(text_parts)
            elif msg.role != "tool":
                entry["content"] = ""
            if tool_calls_out:
                entry["tool_calls"] = tool_calls_out
                if "content" in entry and not entry["content"]:
                    del entry["content"]

            # Only emit the assistant/user/system msg if it has any content.
            has_payload = bool(text_parts) or bool(tool_calls_out)
            if has_payload or msg.role == "system":
                wire_messages.append(entry)
            wire_messages.extend(tool_results)

        body: dict[str, Any] = {"messages": wire_messages}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        return body

    # ---- from_wire -------------------------------------------------------

    @staticmethod
    def from_wire(response: dict[str, Any]) -> ProviderResponse:
        choices = response.get("choices") or []
        choice = choices[0] if choices else {}
        msg = choice.get("message", {}) or {}
        finish = choice.get("finish_reason", "") or ""

        blocks: list[Any] = []
        text = msg.get("content")
        if isinstance(text, str) and text:
            blocks.append(TextBlock(text=text))

        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {}) or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            blocks.append(
                ToolCallBlock(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    args=dict(args) if isinstance(args, dict) else {},
                )
            )

        usage = response.get("usage", {}) or {}
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        cost = Cost(input_tokens=in_tok, output_tokens=out_tok, usd_in=0.0, usd_out=0.0)
        message = CanonicalMessage(
            role="assistant",
            content=tuple(blocks),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                ts=0.0,
                model_id=response.get("model"),
                cost=cost,
                provenance="openai",
            ),
        )
        return ProviderResponse(
            message=message,
            stop_reason=finish,
            cost=cost,
            raw_id=response.get("id", ""),
        )

    # ---- complete --------------------------------------------------------

    async def complete(
        self,
        messages: tuple[CanonicalMessage, ...],
        tools: tuple[ToolSpec, ...],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        cache_breakpoints: tuple[int, ...] = (),
    ) -> ProviderResponse:
        api_key = self._resolve_key()
        body = self.to_wire(messages, tools, cache_breakpoints=cache_breakpoints)
        body["model"] = self.model_id
        body["max_tokens"] = max_tokens
        body["temperature"] = temperature

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        last_exc: BaseException | None = None
        decoded: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    resp = await client.post(url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    if attempt >= _MAX_RETRIES:
                        raise
                    await _sleep_with_jitter(attempt)
                    continue
                if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                    await _sleep_with_jitter(attempt)
                    continue
                resp.raise_for_status()
                decoded = resp.json()
                break
            else:  # pragma: no cover
                assert last_exc is not None
                raise last_exc

        response = self.from_wire(decoded)
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
