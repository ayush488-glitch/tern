"""S12 / D4 — render a session to a single HTML notes artifact.

Reads turn-objects (M7 / S10 store) plus free-form Notes (S12 store) and
emits one self-contained `notes.html`. Same b&w / serif-display aesthetic
as `docs/architecture.html`. No JS, no external assets — opens cleanly in
any browser, prints clean to PDF, survives a network outage.

Why server-side render: per ADR-0007 we want the artifact to be a static
file the model can show off (drop it in docs/, link it from chat). Going
through a templating engine would pull a dep for ~one template; raw f-strings
keep the surface small and easy to audit.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from tern.core.canonical import (
    ContentBlock,
    ImageBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from tern.notes.store import Note, read_notes
from tern.obs.paths import project_dir
from tern.obs.store import TurnObject, read_session_head, walk_chain


def render_html(
    session_id: str,
    *,
    cwd: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """Render the session's turn graph + notes to HTML.

    Default output path: `<project_dir>/notes/<session_id>.html`. Pass
    `out_path` (e.g. `repo/docs/notes.html`) to override.
    """
    head = read_session_head(session_id, cwd=cwd)
    chain: list[TurnObject] = walk_chain(head, cwd=cwd) if head else []
    notes = read_notes(session_id, cwd=cwd)

    if out_path is None:
        out_path = project_dir(cwd) / "notes" / f"{session_id}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_HTML(session_id, chain, notes), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _HTML(session_id: str, chain: list[TurnObject], notes: tuple[Note, ...]) -> str:
    """The whole document as one string. Keep it boring."""
    title = f"tern — session {session_id}"
    rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    summary = _summary_row(chain, notes)
    notes_section = _notes_block(notes)
    transcript = _transcript_block(chain)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1280">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
  <div class="masthead">
    <h1>tern <em>notes</em></h1>
    <div class="meta">
      <div>session</div>
      <div class="v">{html.escape(session_id)}</div>
      <div>rendered</div>
      <div class="v">{html.escape(rendered_at)}</div>
    </div>
  </div>
  <p class="lede">A live HTML artifact of one Tern session — every turn object
  in the graph, every note the agent appended, frozen to a static file.</p>

  <div class="section">
    <div class="section-head"><span class="num">§ 1</span><span class="title">summary</span></div>
    {summary}
  </div>

  <div class="section">
    <div class="section-head"><span class="num">§ 2</span><span class="title">notes</span></div>
    {notes_section}
  </div>

  <div class="section">
    <div class="section-head"><span class="num">§ 3</span><span class="title">transcript</span></div>
    {transcript}
  </div>
</div>
</body>
</html>
"""


def _summary_row(chain: list[TurnObject], notes: tuple[Note, ...]) -> str:
    n_user = sum(1 for o in chain if o.role == "user")
    n_asst = sum(1 for o in chain if o.role == "assistant")
    n_tool = sum(1 for o in chain if o.role == "tool")
    total = sum((o.cost.usd_total for o in chain if o.cost), 0.0)
    cells = [
        ("turns", str(len(chain))),
        ("user", str(n_user)),
        ("assistant", str(n_asst)),
        ("tool", str(n_tool)),
        ("notes", str(len(notes))),
        ("cost", f"${total:.4f}"),
    ]
    inner = "".join(
        f'<div class="kpi"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}</div></div>'
        for k, v in cells
    )
    return f'<div class="kpis">{inner}</div>'


def _notes_block(notes: tuple[Note, ...]) -> str:
    if not notes:
        return '<p class="empty">no notes appended this session.</p>'
    rows: list[str] = []
    for n in notes:
        ts = (
            datetime.fromtimestamp(n.ts, tz=timezone.utc).strftime("%H:%M:%S")
            if n.ts
            else "—"
        )
        tags = (
            "  ".join(f'<span class="tag">#{html.escape(t)}</span>' for t in n.tags)
            if n.tags
            else ""
        )
        rows.append(
            f'<li><span class="meta">[turn {n.turn_idx} · {ts}]</span> '
            f"{html.escape(n.text)}{(' ' + tags) if tags else ''}</li>"
        )
    return f'<ul class="notes">{"".join(rows)}</ul>'


def _transcript_block(chain: list[TurnObject]) -> str:
    if not chain:
        return '<p class="empty">no turns recorded yet.</p>'
    out: list[str] = []
    for o in chain:
        body = "".join(_render_block(b) for b in o.content)
        meta_bits: list[str] = [f"role={o.role}"]
        if o.turn_idx is not None:
            meta_bits.append(f"turn={o.turn_idx}")
        if o.model_id:
            meta_bits.append(f"model={o.model_id}")
        if o.cost:
            meta_bits.append(
                f"in={o.cost.input_tokens} out={o.cost.output_tokens} "
                f"${o.cost.usd_total:.4f}"
            )
        meta = " · ".join(html.escape(s) for s in meta_bits)
        out.append(
            f'<article class="turn turn-{o.role}">'
            f'<header class="turn-meta">{meta}</header>'
            f'<div class="turn-body">{body}</div>'
            f"</article>"
        )
    return "".join(out)


def _render_block(b: ContentBlock) -> str:
    if isinstance(b, TextBlock):
        return f'<p class="text">{html.escape(b.text)}</p>'
    if isinstance(b, ToolCallBlock):
        args = html.escape(repr(b.args))
        return (
            f'<div class="tool-call">→ <span class="name">{html.escape(b.name)}'
            f'</span><pre>{args}</pre></div>'
        )
    if isinstance(b, ToolResultBlock):
        css = "tool-result err" if not b.ok else "tool-result"
        return (
            f'<div class="{css}">← <span class="name">tool result</span>'
            f"<pre>{html.escape(b.content)}</pre></div>"
        )
    if isinstance(b, ImageBlock):
        return '<div class="image-block">[image]</div>'
    return f'<pre class="unknown">{html.escape(repr(b))}</pre>'


# ---------------------------------------------------------------------------
# styles — same broadsheet voice as architecture.html, condensed
# ---------------------------------------------------------------------------

_CSS = """
:root{--ink:#000;--paper:#fff;--hair:1px;--rule:1.25px;--thick:2px;
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --serif:"iA Writer Quattro",Charter,"Iowan Old Style",Georgia,serif;}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--paper);color:var(--ink);
  font-family:var(--mono);-webkit-font-smoothing:antialiased}
.page{max-width:1480px;margin:0 auto;padding:64px 56px 80px}
.masthead{border-top:var(--thick) solid var(--ink);
  border-bottom:var(--hair) solid var(--ink);padding:28px 0 24px;
  display:grid;grid-template-columns:1fr auto;align-items:end;gap:32px}
.masthead h1{font-family:var(--serif);font-weight:400;font-size:88px;
  line-height:0.92;letter-spacing:-0.02em;margin:0}
.masthead h1 em{font-style:italic;font-weight:400}
.masthead .meta{font-size:11px;line-height:1.5;text-align:right;
  text-transform:uppercase;letter-spacing:0.08em}
.masthead .meta .v{font-family:var(--mono);text-transform:none;letter-spacing:0}
.lede{margin:22px 0 0;font-family:var(--serif);font-style:italic;
  font-size:19px;line-height:1.5;max-width:940px}
.section{margin-top:64px}
.section-head{display:grid;grid-template-columns:60px 1fr;align-items:baseline;
  border-bottom:var(--hair) solid var(--ink);padding-bottom:8px;margin-bottom:28px}
.section-head .num{font-size:11px;letter-spacing:0.08em}
.section-head .title{font-family:var(--serif);font-size:28px;letter-spacing:-0.01em}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);
  border:var(--hair) solid var(--ink)}
.kpi{padding:18px 16px;border-right:var(--hair) solid var(--ink)}
.kpi:last-child{border-right:0}
.kpi .k{font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
  margin-bottom:8px}
.kpi .v{font-family:var(--serif);font-size:24px;letter-spacing:-0.01em}
.notes{list-style:none;margin:0;padding:0;font-family:var(--serif);
  font-size:15px;line-height:1.55}
.notes li{padding:10px 0;border-bottom:var(--hair) dashed #888}
.notes li:last-child{border-bottom:0}
.notes .meta{font-family:var(--mono);font-size:11px;color:#444;margin-right:8px}
.notes .tag{font-family:var(--mono);font-size:10px;letter-spacing:0.06em;
  color:#444;border:var(--hair) solid #444;padding:1px 6px;margin-left:4px}
.empty{font-family:var(--serif);font-style:italic;color:#666}
.turn{border-top:var(--hair) solid var(--ink);padding:18px 0}
.turn-meta{font-size:10px;letter-spacing:0.08em;text-transform:uppercase;
  color:#444;margin-bottom:8px}
.turn-user .turn-body{font-family:var(--serif);font-size:15px;line-height:1.55}
.turn-assistant .turn-body{font-family:var(--mono);font-size:13px;line-height:1.55}
.turn-tool .turn-body{font-family:var(--mono);font-size:12px;color:#222}
.turn-body p.text{margin:0 0 8px;white-space:pre-wrap}
.tool-call,.tool-result{margin:6px 0;border-left:var(--rule) solid var(--ink);
  padding:6px 10px;background:#f6f6f6}
.tool-result.err{background:#fdecec}
.tool-call .name,.tool-result .name{font-weight:600}
.tool-call pre,.tool-result pre{margin:4px 0 0;font-size:11px;
  white-space:pre-wrap;word-break:break-word}
"""

__all__ = ["render_html"]
