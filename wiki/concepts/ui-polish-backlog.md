---
title: UI polish backlog (defer to end)
type: concept
created: 2026-05-27
updated: 2026-05-27
tags: [ui, repl, polish, deferred]
---

# UI polish backlog

Captured at end of S9.5. Decision: defer all of this until after S10–S13 land,
because the REPL render surface keeps changing as we add replay/branch (S10),
skills (S11), live notes artifact (S12), browser tool (S13). Polishing now
would churn.

## Backlog

- **Session header banner** on chat start — model, mode, repo path, session id.
- **Cost ribbon** — running $ total in a footer line, not just per-turn.
- **Prompt glyph + color** — `»` → `❯` in cyan (Claude Code feel).
- **Tool one-liners** → collapsible boxed blocks when output > N bytes.
- **Diff panel** — side-by-side mode for big edits; theme match repo language.
- **Pre-stream spinner** — between `LLMRequested` and first delta so dead air
  doesn't feel hung. Time-to-first-token can be 1–3s on Bedrock cold path.
- **Slash commands styled consistently** — `/help`, `/spans`, `/cost`, `/clear`.
- **Markdown code-block rendering** inside the streaming Live region. Currently
  the assistant message renders as Markdown only after the stream closes; mid-
  stream we show plain text. Investigate: rich.markdown chunked render.
- **`--no-color` / `NO_COLOR` env** — full end-to-end respect.
- **Width-aware wrapping** for the diff panel on narrow terminals (<100 cols).

## Why end, not now

1. Each S10–S13 milestone adds new event types (`SessionForked`, `SkillLoaded`,
   `NoteUpdated`, `BrowserAction`). The renderer dispatch (`_StreamRenderer.feed`)
   will grow new branches; styling those before they exist is wasted work.
2. The shape of `ToolCalled` / `ToolReturned` may change once we wire >2 tools
   (S13 browser tool will need streaming output, not a single bytes-out count).
3. Polish is judgment-heavy — once we see all event types rendered together
   (post-S13), we can pick a coherent palette and density in one pass instead
   of bikeshedding per session.

## When to revisit

After S13 lands. Add a polish session (call it S14 or "M11.5") with this file
as the spec.
