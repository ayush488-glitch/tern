"""Banner builder for SO lookup results (S20).

Follows the same banner shape as REPO MEMORY and SIMILAR PAST TURNS.
The banner is injected into the next turn's system prompt when the
previous turn had error_count >= 1.
"""
from __future__ import annotations

from tern.lookup.search import SOHit

_MAX_PREVIEW = 600  # chars of answer body shown in the banner


def build_so_banner(hits: list[SOHit]) -> str:
    """Render a SIMILAR ERRORS (Stack Overflow) banner for system prompt injection.

    Returns empty string when hits is empty.
    """
    if not hits:
        return ""

    lines: list[str] = [
        "══════════════ SIMILAR ERRORS (Stack Overflow) ══════════════",
    ]
    for i, hit in enumerate(hits, 1):
        answered = "answered" if hit.is_answered else "unanswered"
        lines.append(f"\n[{i}] {hit.title}")
        lines.append(f"    score={hit.score}  {answered}  {hit.link}")
        if hit.tags:
            lines.append(f"    tags: {', '.join(hit.tags[:5])}")
        if hit.answer_preview:
            preview = hit.answer_preview[:_MAX_PREVIEW]
            # indent each line of the preview
            indented = "\n    ".join(preview.splitlines())
            lines.append(f"    ---\n    {indented}")
    return "\n".join(lines)
