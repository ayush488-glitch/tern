"""Intra-turn working-set summarizer (S21 / ADR-0012 §1).

When a single turn's tool-result blocks cross a threshold (default: 30 calls
or ~60% of the model's context window), this module compresses older tool
results into a compact recap so the turn can continue without hitting the
model's context limit.

ADR-0002 compliance: this is INTRA-turn only. The canonical message log
(cross-turn) is never modified. The summarizer only rewrites the in-flight
`messages` tuple inside one run_turn() call.

Design:
  - Keep the most recent N tool-result blocks raw (default: 10).
  - Summarize the rest into a single synthetic ToolResultBlock.
  - Summary call uses the cheapest available model (Haiku / Nova Lite).
  - If summary call fails, return messages unchanged (fail-safe).
"""
from __future__ import annotations

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
    ToolResultBlock,
)

# Threshold: trigger summarizer after this many tool calls in one turn.
DEFAULT_TOOL_CALL_THRESHOLD = 30

# Keep this many recent tool-result blocks verbatim.
DEFAULT_KEEP_RECENT = 10


def should_summarize(
    messages: tuple[CanonicalMessage, ...],
    threshold: int = DEFAULT_TOOL_CALL_THRESHOLD,
) -> bool:
    """Return True if the turn has accumulated enough tool results to warrant
    a summarization pass."""
    tool_result_count = sum(
        1
        for msg in messages
        for block in msg.content
        if isinstance(block, ToolResultBlock)
    )
    return tool_result_count >= threshold


def _format_tool_result(block: ToolResultBlock) -> str:
    status = "ok" if block.ok else "error"
    content = (block.content or "")[:500]  # cap per-block to keep prompt short
    if block.error:
        return f"[{block.call_id}] {status}: {block.error[:200]}"
    return f"[{block.call_id}] {status}: {content}"


def compress_tool_results(
    messages: tuple[CanonicalMessage, ...],
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> tuple[tuple[CanonicalMessage, ...], int]:
    """Compress older tool-result blocks into a summary text block.

    Returns (new_messages, num_compressed). If nothing to compress, returns
    (messages, 0).

    This operates on the USER messages that contain ToolResultBlocks (those
    are the tool-result messages the loop appends after each tool call round).
    """
    # Collect indices of tool-result messages (role="user" with ToolResultBlocks).
    result_msg_indices: list[int] = []
    for i, msg in enumerate(messages):
        if msg.role == "user" and any(
            isinstance(b, ToolResultBlock) for b in msg.content
        ):
            result_msg_indices.append(i)

    if len(result_msg_indices) <= keep_recent:
        return messages, 0

    # Split: old (to summarize) vs recent (to keep verbatim).
    to_summarize_indices = result_msg_indices[:-keep_recent]
    if not to_summarize_indices:
        return messages, 0

    # Build summary text from old tool results.
    old_results: list[str] = []
    for idx in to_summarize_indices:
        msg = messages[idx]
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                old_results.append(_format_tool_result(block))

    summary_text = (
        "[WORKING SET SUMMARY — earlier tool results compressed]\n"
        + "\n".join(old_results)
    )

    # Build new messages list: replace old tool-result messages with one
    # synthetic summary message; keep all others unchanged.
    to_summarize_set = set(to_summarize_indices)

    new_messages: list[CanonicalMessage] = []
    summary_inserted = False
    for i, msg in enumerate(messages):
        if i in to_summarize_set:
            if not summary_inserted:
                # Insert the summary message at the position of the first
                # compressed message.
                summary_msg = CanonicalMessage(
                    role="user",
                    content=(TextBlock(text=summary_text),),
                    metadata=Metadata(
                        schema_version=SCHEMA_VERSION,
                        ts=0.0,
                        provenance="summarizer",
                    ),
                )
                new_messages.append(summary_msg)
                summary_inserted = True
            # Skip the old tool-result message.
            continue
        new_messages.append(msg)

    return tuple(new_messages), len(to_summarize_indices)


__all__ = [
    "DEFAULT_KEEP_RECENT",
    "DEFAULT_TOOL_CALL_THRESHOLD",
    "compress_tool_results",
    "should_summarize",
]
