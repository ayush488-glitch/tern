"""Tests for the Bedrock-Anthropic adapter.

NO live network. We exercise pure to_wire/from_wire and the cache-breakpoint
shape. The complete() call is structural-only: we mock boto3.client.

This file pins the hard parts of ADR-0004:
  - system role lifted to top-level "system" field (NOT a message)
  - ToolCallBlock -> Anthropic tool_use block
  - ToolResultBlock -> Anthropic tool_result block
  - ToolSpec -> bare {name, description, input_schema} (NOT wrapped)
  - cache_breakpoints applied at the right indices
  - canonical -> wire -> canonical roundtrip via a realistic fixture response
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from tern.adapters.bedrock_anthropic import BedrockAnthropicAdapter
from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    ImageBlock,
    Metadata,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)


def _meta() -> Metadata:
    return Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test")


def _user(text: str) -> CanonicalMessage:
    return CanonicalMessage(role="user", content=(TextBlock(text=text),), metadata=_meta())


def _assistant(*blocks: object) -> CanonicalMessage:
    return CanonicalMessage(
        role="assistant",
        content=tuple(blocks),  # type: ignore[arg-type]
        metadata=_meta(),
    )


def _system(text: str) -> CanonicalMessage:
    return CanonicalMessage(role="system", content=(TextBlock(text=text),), metadata=_meta())


def _tool_msg(call_id: str, content: str, ok: bool = True) -> CanonicalMessage:
    return CanonicalMessage(
        role="tool",
        content=(ToolResultBlock(call_id=call_id, ok=ok, content=content),),
        metadata=_meta(),
    )


# ---------------------------------------------------------------------------
# system role lifting
# ---------------------------------------------------------------------------


def test_system_message_is_lifted_to_top_level_system_field() -> None:
    msgs = (_system("you are tern"), _user("hi"))
    wire = BedrockAnthropicAdapter.to_wire(msgs)
    assert wire["system"] == "you are tern"
    # only the user message remains in messages[]
    assert len(wire["messages"]) == 1
    assert wire["messages"][0]["role"] == "user"


def test_no_system_message_omits_system_field() -> None:
    wire = BedrockAnthropicAdapter.to_wire((_user("hi"),))
    assert "system" not in wire or wire["system"] == ""


def test_multiple_system_messages_concatenate() -> None:
    msgs = (_system("part one"), _system("part two"), _user("hi"))
    wire = BedrockAnthropicAdapter.to_wire(msgs)
    assert "part one" in wire["system"]
    assert "part two" in wire["system"]


# ---------------------------------------------------------------------------
# basic message mapping
# ---------------------------------------------------------------------------


def test_user_text_message_maps_directly() -> None:
    wire = BedrockAnthropicAdapter.to_wire((_user("hello"),))
    assert wire["messages"][0] == {
        "role": "user",
        "content": [{"type": "text", "text": "hello"}],
    }


def test_assistant_text_message_maps_directly() -> None:
    wire = BedrockAnthropicAdapter.to_wire((_assistant(TextBlock(text="ok")),))
    assert wire["messages"][0] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
    }


# ---------------------------------------------------------------------------
# tool_call mapping
# ---------------------------------------------------------------------------


def test_tool_call_block_maps_to_tool_use_block() -> None:
    msg = _assistant(
        TextBlock(text="calling read_file"),
        ToolCallBlock(id="call_1", name="read_file", args={"path": "/x"}),
    )
    wire = BedrockAnthropicAdapter.to_wire((msg,))
    blocks = wire["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "calling read_file"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "read_file",
        "input": {"path": "/x"},
    }


# ---------------------------------------------------------------------------
# tool_result mapping
# ---------------------------------------------------------------------------


def test_tool_result_block_maps_to_tool_result_block_under_user_role() -> None:
    """Anthropic puts tool_result blocks inside a user-role message."""
    msg = _tool_msg(call_id="call_1", content="file contents here")
    wire = BedrockAnthropicAdapter.to_wire((msg,))
    out = wire["messages"][0]
    assert out["role"] == "user"
    assert out["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": "file contents here",
    }


def test_tool_result_failure_sets_is_error_flag() -> None:
    msg = _tool_msg(call_id="call_2", content="boom", ok=False)
    wire = BedrockAnthropicAdapter.to_wire((msg,))
    block = wire["messages"][0]["content"][0]
    assert block["is_error"] is True


# ---------------------------------------------------------------------------
# image blocks
# ---------------------------------------------------------------------------


def test_image_block_maps_to_anthropic_image_shape() -> None:
    msg = CanonicalMessage(
        role="user",
        content=(ImageBlock(media_type="image/png", data_b64="aGVsbG8="),),
        metadata=_meta(),
    )
    wire = BedrockAnthropicAdapter.to_wire((msg,))
    block = wire["messages"][0]["content"][0]
    assert block == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "aGVsbG8=",
        },
    }


# ---------------------------------------------------------------------------
# tool spec wrapping
# ---------------------------------------------------------------------------


def test_tool_spec_wraps_as_bare_anthropic_shape_not_openai_function_wrapper() -> None:
    spec = ToolSpec(
        name="read_file",
        description="Read a file.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    wire = BedrockAnthropicAdapter.to_wire((_user("hi"),), tools=(spec,))
    assert wire["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    # explicitly NOT the OpenAI {"type": "function", "function": {...}} shape
    assert "function" not in wire["tools"][0]


# ---------------------------------------------------------------------------
# cache breakpoints
# ---------------------------------------------------------------------------


def test_cache_breakpoints_marked_at_requested_indices() -> None:
    msgs = (_user("a"), _user("b"), _user("c"))
    wire = BedrockAnthropicAdapter.to_wire(msgs, cache_breakpoints=(0, 2))
    # indices 0 and 2 should have a cache_control flag on their last block
    assert wire["messages"][0]["content"][-1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in wire["messages"][1]["content"][-1]
    assert wire["messages"][2]["content"][-1].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# from_wire — parse a realistic Anthropic Messages response
# ---------------------------------------------------------------------------


def _fake_anthropic_response(text: str = "hello") -> dict[str, Any]:
    return {
        "id": "msg_01ABCDEF",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-20250514",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_from_wire_extracts_text_and_cost_and_stop_reason() -> None:
    raw = _fake_anthropic_response("hi from claude")
    resp = BedrockAnthropicAdapter.from_wire(raw)
    assert resp.message.role == "assistant"
    assert resp.message.content[0] == TextBlock(text="hi from claude")
    assert resp.cost.input_tokens == 10
    assert resp.cost.output_tokens == 5
    assert resp.stop_reason == "end_turn"
    assert resp.raw_id == "msg_01ABCDEF"


def test_from_wire_handles_tool_use_response_block() -> None:
    raw = {
        "id": "msg_xyz",
        "role": "assistant",
        "model": "claude",
        "content": [
            {"type": "text", "text": "let me check"},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_file",
                "input": {"path": "/etc/hosts"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 20, "output_tokens": 8},
    }
    resp = BedrockAnthropicAdapter.from_wire(raw)
    assert isinstance(resp.message.content[1], ToolCallBlock)
    tc: ToolCallBlock = resp.message.content[1]  # type: ignore[assignment]
    assert tc.id == "toolu_1"
    assert tc.name == "read_file"
    assert tc.args == {"path": "/etc/hosts"}


# ---------------------------------------------------------------------------
# roundtrip — canonical -> wire -> canonical -> semantic equivalence
# ---------------------------------------------------------------------------


def test_assistant_message_with_tool_call_roundtrips_through_wire() -> None:
    """Per ADR-0004: roundtrip(canonical -> wire -> canonical) must preserve meaning.

    We don't compare metadata (timestamps, cost) — those are response-side
    fields. We compare role + content blocks.
    """
    original = _assistant(
        TextBlock(text="calling tool"),
        ToolCallBlock(id="t1", name="read_file", args={"path": "/x"}),
    )
    wire = BedrockAnthropicAdapter.to_wire((original,))
    # synthesize an Anthropic-shape response from the wire'd assistant message
    fake = {
        "id": "msg_rt",
        "role": "assistant",
        "model": "claude",
        "content": wire["messages"][0]["content"],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    resp = BedrockAnthropicAdapter.from_wire(fake)
    assert resp.message.role == original.role
    assert resp.message.content == original.content


# ---------------------------------------------------------------------------
# complete() is wired to boto3 — structural-only test, fully mocked
# ---------------------------------------------------------------------------


def test_complete_calls_bedrock_runtime_invoke_model_and_returns_provider_response() -> None:
    import json as _json

    fake_body = _json.dumps(_fake_anthropic_response("from bedrock")).encode("utf-8")
    fake_stream = MagicMock()
    fake_stream.read.return_value = fake_body
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {"body": fake_stream}

    with patch("tern.adapters.bedrock_anthropic.boto3") as fake_boto3:
        fake_boto3.client.return_value = fake_client
        adapter = BedrockAnthropicAdapter(
            model_id="anthropic.claude-sonnet-4-20250514-v1:0"
        )
        import asyncio

        resp = asyncio.run(
            adapter.complete(
                messages=(_user("hi"),),
                tools=(),
                max_tokens=128,
            )
        )

    fake_client.invoke_model.assert_called_once()
    kwargs = fake_client.invoke_model.call_args.kwargs
    assert kwargs["modelId"] == "anthropic.claude-sonnet-4-20250514-v1:0"
    assert resp.message.content[0] == TextBlock(text="from bedrock")
    assert resp.stop_reason == "end_turn"



def test_tool_result_failure_with_empty_content_falls_back_to_error() -> None:
    """Bedrock rejects empty content when is_error=true. Adapter must backfill."""
    from tern.adapters.bedrock_anthropic import _tool_result_to_wire
    from tern.core.canonical import ToolResultBlock

    b = ToolResultBlock(call_id="t1", ok=False, content="", error="path escapes repo root")
    wire = _tool_result_to_wire(b)
    assert wire["is_error"] is True
    assert wire["content"] == "path escapes repo root"

    b2 = ToolResultBlock(call_id="t2", ok=False, content="", error=None)
    wire2 = _tool_result_to_wire(b2)
    assert wire2["content"]  # never empty
