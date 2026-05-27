"""Tests for M4 canonical messages — the vendor-neutral message log.

The lock: internal canonical message log != provider wire format.
These tests pin the invariants D1 (cost routing) and D3 (replay/branch) depend on:
  - frozen + hashable
  - byte-stable JSON
  - content-addressable hash
  - additive evolution via schema_version
  - JSON roundtrip identity for every ContentBlock variant
"""

from __future__ import annotations

import dataclasses
import json

import pytest

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
    content_hash,
    from_json,
    stable_json,
)


def _meta(**overrides: object) -> Metadata:
    base = dict(
        schema_version=SCHEMA_VERSION,
        ts=1716800000.0,
        model_id="anthropic.claude-sonnet-4-20250514-v1:0",
        cost=None,
        seed=None,
        provenance="test",
    )
    base.update(overrides)
    return Metadata(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Frozen + hashable
# ---------------------------------------------------------------------------


def test_canonical_message_is_frozen() -> None:
    msg = CanonicalMessage(
        role="user",
        content=(TextBlock(text="hi"),),
        metadata=_meta(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.role = "assistant"  # type: ignore[misc]


def test_text_block_is_frozen() -> None:
    block = TextBlock(text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.text = "bye"  # type: ignore[misc]


def test_messages_with_identical_content_have_identical_hash() -> None:
    a = CanonicalMessage(role="user", content=(TextBlock(text="hi"),), metadata=_meta())
    b = CanonicalMessage(role="user", content=(TextBlock(text="hi"),), metadata=_meta())
    assert content_hash(a) == content_hash(b)


def test_one_byte_change_produces_different_hash() -> None:
    a = CanonicalMessage(role="user", content=(TextBlock(text="hi"),), metadata=_meta())
    b = CanonicalMessage(role="user", content=(TextBlock(text="hI"),), metadata=_meta())
    assert content_hash(a) != content_hash(b)


# ---------------------------------------------------------------------------
# Byte-stable JSON
# ---------------------------------------------------------------------------


def test_stable_json_has_no_whitespace_and_sorted_keys() -> None:
    msg = CanonicalMessage(
        role="user",
        content=(TextBlock(text="hi"),),
        metadata=_meta(),
    )
    blob = stable_json(msg)
    assert " " not in blob.replace('"hi"', "")  # no incidental whitespace
    # keys must be lexicographically sorted at every level: 'content' before 'metadata' before 'role'
    decoded = json.loads(blob)
    assert list(decoded.keys()) == sorted(decoded.keys())


def test_stable_json_is_byte_identical_across_calls() -> None:
    msg = CanonicalMessage(
        role="assistant",
        content=(
            TextBlock(text="ok"),
            ToolCallBlock(id="c1", name="read_file", args={"path": "/tmp/x", "offset": 1}),
        ),
        metadata=_meta(),
    )
    a = stable_json(msg)
    b = stable_json(msg)
    assert a == b
    # also verify args dict is sorted (path before offset alphabetically: o < p, so offset first)
    assert '"args":{"offset":1,"path":"/tmp/x"}' in a


# ---------------------------------------------------------------------------
# JSON roundtrip — every block type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        TextBlock(text="plain text"),
        ToolCallBlock(id="call_1", name="search", args={"query": "x", "limit": 5}),
        ToolResultBlock(
            call_id="call_1", ok=True, content="result body", error=None, metadata={}
        ),
        ToolResultBlock(
            call_id="call_2",
            ok=False,
            content="",
            error="boom",
            metadata={"exit_code": 1},
        ),
        ImageBlock(media_type="image/png", data_b64="aGVsbG8="),
    ],
)
def test_block_roundtrips_through_json(block: object) -> None:
    msg = CanonicalMessage(role="user", content=(block,), metadata=_meta())  # type: ignore[arg-type]
    rebuilt = from_json(stable_json(msg))
    assert rebuilt == msg
    assert content_hash(rebuilt) == content_hash(msg)


def test_full_message_with_mixed_blocks_roundtrips() -> None:
    msg = CanonicalMessage(
        role="assistant",
        content=(
            TextBlock(text="I will call a tool."),
            ToolCallBlock(id="c1", name="read_file", args={"path": "x.py"}),
        ),
        metadata=_meta(
            cost=Cost(input_tokens=100, output_tokens=20, usd_in=0.0003, usd_out=0.00015),
        ),
    )
    rebuilt = from_json(stable_json(msg))
    assert rebuilt == msg


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_schema_version_is_stamped_in_metadata() -> None:
    msg = CanonicalMessage(role="user", content=(TextBlock(text="hi"),), metadata=_meta())
    decoded = json.loads(stable_json(msg))
    assert decoded["metadata"]["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Surface: ToolSpec, Capabilities, Cost, ProviderResponse construct cleanly
# ---------------------------------------------------------------------------


def test_tool_spec_is_frozen_and_carries_json_schema() -> None:
    spec = ToolSpec(
        name="read_file",
        description="Read a file.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "x"  # type: ignore[misc]
    assert spec.input_schema["type"] == "object"


def test_capabilities_defaults_are_conservative() -> None:
    caps = Capabilities()
    # If a future provider says nothing, assume nothing.
    assert caps.tool_use is False
    assert caps.vision is False
    assert caps.supports_caching is False
    assert caps.max_input_tokens > 0  # must have *some* sane default


def test_provider_response_carries_message_and_cost() -> None:
    msg = CanonicalMessage(role="assistant", content=(TextBlock(text="hi"),), metadata=_meta())
    cost = Cost(input_tokens=10, output_tokens=2, usd_in=0.0001, usd_out=0.00001)
    resp = ProviderResponse(
        message=msg, stop_reason="end_turn", cost=cost, raw_id="msg_abc"
    )
    assert resp.message is msg
    assert resp.cost.input_tokens == 10
    assert resp.stop_reason == "end_turn"
