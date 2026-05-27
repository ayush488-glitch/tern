"""Canonical message log — vendor-neutral, frozen, hashable.

This module is THE LOCK. Per ADR-0004 + concepts/canonical-message-log.md:
the agent core only ever reads or writes these types. Provider adapters
translate to and from this shape via pure functions. Nothing here knows
about Anthropic, OpenAI, or Bedrock.

D1 (cost routing) and D3 (replay/branch) both depend on:
  - frozen + hashable values
  - byte-stable JSON via stable_json()
  - content-addressable hash via content_hash()
  - additive evolution gated by SCHEMA_VERSION

Keep this module pure: stdlib only, no I/O, no provider imports.
"""

from __future__ import annotations

import hashlib
import json
import re as _re
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Schema version. Bump on incompatible changes only; new ContentBlock types
# are additive and do not require a bump.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    kind: Literal["text"] = "text"


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    id: str
    name: str
    args: dict[str, Any]
    kind: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    call_id: str
    ok: bool
    content: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    kind: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True, slots=True)
class ImageBlock:
    media_type: str
    data_b64: str
    kind: Literal["image"] = "image"


ContentBlock = TextBlock | ToolCallBlock | ToolResultBlock | ImageBlock


# ---------------------------------------------------------------------------
# Cost, capabilities, metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cost:
    input_tokens: int
    output_tokens: int
    usd_in: float
    usd_out: float

    @property
    def usd_total(self) -> float:
        return self.usd_in + self.usd_out


@dataclass(frozen=True, slots=True)
class Capabilities:
    tool_use: bool = False
    vision: bool = False
    supports_caching: bool = False
    # Conservative default: assume any modern adapter handles at least 8k tokens.
    # Real adapters override at construction.
    max_input_tokens: int = 8_192


@dataclass(frozen=True, slots=True)
class Metadata:
    schema_version: int
    ts: float
    model_id: str | None = None
    cost: Cost | None = None
    seed: int | None = None
    provenance: str = ""


# ---------------------------------------------------------------------------
# Tool specification — provider-neutral. Adapters wrap this into vendor shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Canonical message
# ---------------------------------------------------------------------------


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    role: Role
    content: tuple[ContentBlock, ...]
    metadata: Metadata


# ---------------------------------------------------------------------------
# Provider response wrapper (returned by ProviderAdapter.complete)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    message: CanonicalMessage
    stop_reason: str
    cost: Cost
    raw_id: str


# ---------------------------------------------------------------------------
# Stable serialization
# ---------------------------------------------------------------------------


def stable_json(msg: CanonicalMessage) -> str:
    """Byte-stable JSON encoding.

    sort_keys + minimal separators makes this hashable: same logical
    message -> same bytes -> same hash, across Python versions and
    PYTHONHASHSEED values. content_hash() depends on this contract.
    """
    return json.dumps(asdict(msg), sort_keys=True, separators=(",", ":"))


def content_hash(msg: CanonicalMessage) -> str:
    """sha256 of the stable-JSON encoding. Used for D3 content addressing."""
    return hashlib.sha256(stable_json(msg).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# JSON -> dataclass rebuild (for replay / wire-driven reconstruction)
# ---------------------------------------------------------------------------


_BLOCK_BY_KIND: dict[str, type[ContentBlock]] = {
    "text": TextBlock,
    "tool_call": ToolCallBlock,
    "tool_result": ToolResultBlock,
    "image": ImageBlock,
}


def _block_from_dict(d: dict[str, Any]) -> ContentBlock:
    kind = d.get("kind")
    cls = _BLOCK_BY_KIND.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise ValueError(f"unknown content block kind: {kind!r}")
    return cls(**d)


def _metadata_from_dict(d: dict[str, Any]) -> Metadata:
    cost_d = d.get("cost")
    cost = Cost(**cost_d) if isinstance(cost_d, dict) else None
    return Metadata(
        schema_version=int(d["schema_version"]),
        ts=float(d["ts"]),
        model_id=d.get("model_id"),
        cost=cost,
        seed=d.get("seed"),
        provenance=d.get("provenance", ""),
    )


def from_json(blob: str) -> CanonicalMessage:
    """Inverse of stable_json. Rebuilds typed blocks from the JSON tree."""
    raw = json.loads(blob)
    if not isinstance(raw, dict):
        raise ValueError("canonical JSON must be an object")
    content_raw = raw.get("content", [])
    if not isinstance(content_raw, list):
        raise ValueError("canonical 'content' must be a list")
    blocks = tuple(_block_from_dict(b) for b in content_raw)
    return CanonicalMessage(
        role=raw["role"],
        content=blocks,
        metadata=_metadata_from_dict(raw["metadata"]),
    )


# ---------------------------------------------------------------------------
# Pseudo-XML tool-call rescue (S15 — notes_append fix)
#
# Some models (Sonnet observed in the wild) ignore the structured tool_use
# protocol and emit literal `<tool_name>...</tool_name>` text instead. The
# loop never sees a ToolCallBlock and the tool is silently skipped. This
# helper rewrites such an assistant message: any text block matching the
# pattern is replaced with a synthetic ToolCallBlock so the loop fires the
# tool. Best-effort, idempotent — if the pattern doesn't match, the message
# is returned unchanged.
# ---------------------------------------------------------------------------


_PSEUDO_XML_RE = _re.compile(
    r"<\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*>(.*?)<\s*/\s*\1\s*>",
    _re.DOTALL,
)


def lift_pseudo_xml_tool_calls(
    msg: CanonicalMessage, allowed_names: frozenset[str]
) -> CanonicalMessage:
    """Promote `<tool>text</tool>` text-blocks into ToolCallBlocks.

    Only names in `allowed_names` are lifted (the registry's tool list), so
    real prose containing < and > stays untouched. The first inner-text
    capture becomes a single-arg payload; tools that want this rescue must
    accept either a `text` arg (notes_append) or unwrap accordingly. For
    other tools we fall back to a positional dict whose only key is `text`,
    which Pydantic will reject — and the loop's existing ValidationError
    path will surface the failure cleanly to the model on the next step.
    """
    if not allowed_names:
        return msg
    new_blocks: list[ContentBlock] = []
    changed = False
    for block in msg.content:
        if not isinstance(block, TextBlock):
            new_blocks.append(block)
            continue
        text = block.text
        # cheap pre-check: any candidate at all?
        if "<" not in text or ">" not in text:
            new_blocks.append(block)
            continue
        # find every match; if one of them is an allowed tool name, lift it
        cursor = 0
        emitted_any = False
        for m in _PSEUDO_XML_RE.finditer(text):
            tool_name = m.group(1)
            if tool_name not in allowed_names:
                continue
            inner = m.group(2).strip()
            # leading prose (before this match) survives as a TextBlock
            prefix = text[cursor : m.start()].strip()
            if prefix:
                new_blocks.append(TextBlock(text=prefix))
            # synthesize a ToolCallBlock with `text` arg (matches notes_append)
            call_id = f"rescue_{_uuid.uuid4().hex[:10]}"
            new_blocks.append(
                ToolCallBlock(id=call_id, name=tool_name, args={"text": inner})
            )
            cursor = m.end()
            emitted_any = True
            changed = True
        if emitted_any:
            tail = text[cursor:].strip()
            if tail:
                new_blocks.append(TextBlock(text=tail))
        else:
            new_blocks.append(block)
    if not changed:
        return msg
    return CanonicalMessage(
        role=msg.role,
        content=tuple(new_blocks),
        metadata=msg.metadata,
    )
