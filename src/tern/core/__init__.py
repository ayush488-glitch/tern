"""Tern core — provider-neutral primitives.

This package owns the canonical types every other module depends on. Concrete
adapters (Bedrock, OpenAI), tools, and storage all import FROM here, never INTO
here. See wiki/decisions/adr-0002-runtime-shape.md and
wiki/decisions/adr-0004-provider-layer.md.
"""

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Capabilities,
    ContentBlock,
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
from tern.core.provider import ProviderAdapter

__all__ = [
    "SCHEMA_VERSION",
    "CanonicalMessage",
    "Capabilities",
    "ContentBlock",
    "Cost",
    "ImageBlock",
    "Metadata",
    "ProviderAdapter",
    "ProviderResponse",
    "TextBlock",
    "ToolCallBlock",
    "ToolResultBlock",
    "ToolSpec",
    "content_hash",
    "from_json",
    "stable_json",
]
