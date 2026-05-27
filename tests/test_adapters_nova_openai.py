"""Tests for the BedrockNovaAdapter and OpenAIAdapter wire (de)serialization.

Both pure-function tests — no boto3 / no httpx network calls.
"""
from __future__ import annotations

from tern.adapters.bedrock_nova import BedrockNovaAdapter
from tern.adapters.openai_adapter import OpenAIAdapter
from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)


def _meta() -> Metadata:
    return Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test")


# ---- Nova ------------------------------------------------------------------


def test_nova_to_wire_basic_text() -> None:
    msgs = (
        CanonicalMessage(role="system", content=(TextBlock(text="be kind"),), metadata=_meta()),
        CanonicalMessage(role="user", content=(TextBlock(text="hi"),), metadata=_meta()),
    )
    wire = BedrockNovaAdapter.to_wire(msgs)
    assert wire["system"] == [{"text": "be kind"}]
    assert wire["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]


def test_nova_to_wire_with_tools() -> None:
    tool = ToolSpec(name="echo", description="echoes", input_schema={"type": "object"})
    wire = BedrockNovaAdapter.to_wire(
        (CanonicalMessage(role="user", content=(TextBlock(text="x"),), metadata=_meta()),),
        (tool,),
    )
    assert wire["toolConfig"]["tools"][0]["toolSpec"]["name"] == "echo"
    assert wire["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"] == {"type": "object"}


def test_nova_from_wire_text_and_toolUse() -> None:
    raw = {
        "output": {"message": {"content": [
            {"text": "hello"},
            {"toolUse": {"toolUseId": "t1", "name": "echo", "input": {"x": 1}}},
        ]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }
    resp = BedrockNovaAdapter.from_wire(raw)
    assert resp.stop_reason == "end_turn"
    assert resp.cost.input_tokens == 10
    assert resp.cost.output_tokens == 5
    blocks = resp.message.content
    assert isinstance(blocks[0], TextBlock) and blocks[0].text == "hello"
    assert isinstance(blocks[1], ToolCallBlock) and blocks[1].name == "echo"
    assert blocks[1].args == {"x": 1}


def test_nova_to_wire_tool_result_becomes_user() -> None:
    msgs = (
        CanonicalMessage(
            role="tool",
            content=(ToolResultBlock(call_id="t1", ok=True, content="42"),),
            metadata=_meta(),
        ),
    )
    wire = BedrockNovaAdapter.to_wire(msgs)
    assert wire["messages"][0]["role"] == "user"
    tr = wire["messages"][0]["content"][0]["toolResult"]
    assert tr["toolUseId"] == "t1"
    assert tr["content"] == [{"text": "42"}]
    assert "status" not in tr  # ok=True -> no status flag


def test_nova_to_wire_tool_result_error_marks_status() -> None:
    msgs = (
        CanonicalMessage(
            role="tool",
            content=(ToolResultBlock(call_id="t1", ok=False, content="boom", error="boom"),),
            metadata=_meta(),
        ),
    )
    wire = BedrockNovaAdapter.to_wire(msgs)
    assert wire["messages"][0]["content"][0]["toolResult"]["status"] == "error"


# ---- OpenAI ----------------------------------------------------------------


def test_openai_to_wire_basic() -> None:
    msgs = (
        CanonicalMessage(role="system", content=(TextBlock(text="sys"),), metadata=_meta()),
        CanonicalMessage(role="user", content=(TextBlock(text="hi"),), metadata=_meta()),
    )
    wire = OpenAIAdapter.to_wire(msgs)
    assert wire["messages"][0] == {"role": "system", "content": "sys"}
    assert wire["messages"][1] == {"role": "user", "content": "hi"}


def test_openai_to_wire_tools_use_function_wrapper() -> None:
    tool = ToolSpec(name="echo", description="d", input_schema={"type": "object"})
    wire = OpenAIAdapter.to_wire(
        (CanonicalMessage(role="user", content=(TextBlock(text="x"),), metadata=_meta()),),
        (tool,),
    )
    assert wire["tools"][0]["type"] == "function"
    assert wire["tools"][0]["function"]["name"] == "echo"
    assert wire["tools"][0]["function"]["parameters"] == {"type": "object"}


def test_openai_to_wire_tool_call_and_result() -> None:
    msgs = (
        CanonicalMessage(
            role="assistant",
            content=(ToolCallBlock(id="c1", name="echo", args={"a": 1}),),
            metadata=_meta(),
        ),
        CanonicalMessage(
            role="tool",
            content=(ToolResultBlock(call_id="c1", ok=True, content="ok"),),
            metadata=_meta(),
        ),
    )
    wire = OpenAIAdapter.to_wire(msgs)
    # assistant entry has tool_calls
    asst = wire["messages"][0]
    assert asst["role"] == "assistant"
    assert asst["tool_calls"][0]["id"] == "c1"
    assert asst["tool_calls"][0]["function"]["name"] == "echo"
    # tool result becomes a separate role=tool message
    tool_msg = wire["messages"][1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == "ok"


def test_openai_from_wire_text_and_tool_call() -> None:
    raw = {
        "id": "chatcmpl-x",
        "model": "gpt-5-mini",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "hello",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": '{"a": 1}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    resp = OpenAIAdapter.from_wire(raw)
    assert resp.stop_reason == "tool_calls"
    assert resp.cost.input_tokens == 7
    assert resp.cost.output_tokens == 3
    blocks = resp.message.content
    assert isinstance(blocks[0], TextBlock) and blocks[0].text == "hello"
    assert isinstance(blocks[1], ToolCallBlock)
    assert blocks[1].args == {"a": 1}


def test_openai_from_wire_handles_missing_arguments() -> None:
    raw = {
        "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "n", "arguments": "garbage"}}
        ]}, "finish_reason": "stop"}],
    }
    resp = OpenAIAdapter.from_wire(raw)
    blocks = resp.message.content
    # text was empty -> no TextBlock; tool call should still come through with empty args
    assert any(isinstance(b, ToolCallBlock) and b.args == {} for b in blocks)
