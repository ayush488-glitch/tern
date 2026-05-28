"""render_recall_banner — format RecallHits as a system-prompt banner."""
from __future__ import annotations

from tern.recall.store import RecallHit

_HEADER = "══════════════ SIMILAR PAST TURNS ══════════════"
_FOOTER = "═" * len(_HEADER)


def render_recall_banner(hits: list[RecallHit]) -> str:
    """Format recall hits as a banner for injection into the system prompt.

    Returns empty string when hits is empty (no tokens wasted).
    """
    if not hits:
        return ""

    lines: list[str] = [_HEADER]
    for i, hit in enumerate(hits, 1):
        sim_pct = f"{hit.similarity * 100:.0f}%"
        lines.append(f"## Hit {i} — {hit.purpose} — similarity {sim_pct}")
        lines.append(f"Prompt: {hit.prompt_preview}")
        lines.append(f"Reply:  {hit.reply_preview}")
        lines.append("")
    lines.append(_FOOTER)
    return "\n".join(lines)
