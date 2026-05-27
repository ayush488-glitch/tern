---
title: S12 — live HTML notes artifact (D4)
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [tern, s12, d4, notes, html]
---

# S12 — live HTML notes artifact (D4)

## Goal
Land D4: a static `notes.html` artifact that the agent regenerates every
turn from the turn-object graph plus a free-form note store. Same b&w
broadsheet aesthetic as `docs/architecture.html`. No JS. No server.

## Built (~75 min)
- `src/tern/notes/store.py` — JSONL append-only note store. `Note`,
  `append_note`, `read_notes`, `notes_path`, `truncate_notes`. Tolerates
  partial trailing lines on read.
- `src/tern/notes/render.py` — `render_html(session_id, cwd, out_path)`.
  Walks the chain via `walk_chain(read_session_head(...))`, reads notes,
  emits one self-contained HTML doc with inline CSS. Three sections:
  summary KPIs, notes list, role-tagged transcript with text + tool-call +
  tool-result blocks. HTML-escapes every model-controlled string.
- `src/tern/tools/native/notes_append.py` — `NotesAppendTool`. Pydantic v2
  args (`extra="forbid"`), non-destructive annotations, stamps rows with
  `ctx.session_id` + `ctx.turn_idx`. Wired into the chat registry alongside
  `read_file` + `edit_block`.
- `src/tern/cli.py` — render hook after `tern run` persists the assistant
  reply; new `tern notes [session] [--out] [--open]` command for manual
  renders.
- `src/tern/ui/app.py` — render hook after each chat turn. Best-effort
  (render failure logs, doesn't break the loop).
- `tests/test_notes.py` — 12 new tests: store roundtrip, partial-line
  tolerance, truncate, render sections, HTML escaping, empty-session,
  custom out path, tool integration, annotations, args validation, native
  exports.

## Demoable end-to-end

```
$ TERN_LIVE=1 tern run "say hi in two words"
· us.anthropic.claude-sonnet-4-20250514-v1:0  in=53 out=6 $0.0000
Hello there!
notes: /Users/ayushsingh/.tern/projects/Users-ayushsingh-Desktop-coding-agent/notes/7b98a9e774b8.html

session 7b98a9e774b8  ·  cost $0.0000
```

The HTML opens in any browser, prints clean to PDF, mirrors
`architecture.html`'s typography.

## Gates
- `pytest -q` 137/137 ✅ (was 125 entering S12; +12)
- `ruff check src tests` ✅ (one auto-fix run, then clean)
- `mypy --strict src` ✅ (35 src files)
- `tern --version` ✅
- Live Bedrock smoke ✅ — artifact written + path printed.

## Decisions
- Store under `~/.tern/projects/<sanitized>/notes/`, NOT in the repo. Keeps
  `tern run` side-effect-free against the user's tree. `tern notes --out
  docs/notes.html` opts in when desired.
- Notes are orthogonal to turn-object hashes — adding a note doesn't
  invalidate replay (ADR-0007 §Consequences).
- HTML rendering is server-side, no JS. Inline CSS. One static file.
- Best-effort render hook — never breaks the loop on render failure.
- `notes_append` is non-destructive (writes only to `~/.tern`), so no
  approval prompt in default mode. `tern run` still runs tool-less for
  now (existing pre-S12 limitation), but the render hook fires there too.

## Pitfalls caught
- Initial draft used wrong attribute names on `Cost` (`tokens_in`,
  `usd_in/out` separately) and `ToolCallBlock` (`input` vs `args`) —
  Pyright flagged before tests. Resolved by reading
  `src/tern/core/canonical.py` once and using `usd_total`, `args`, `ok`.
- `bare except Exception` in tests trips ruff B017; switched to importing
  `pydantic.ValidationError` directly.

## Next
S13 · M9 + M10 — browser + MCP (D5 + D6). browser-use as one tool;
ClientSessionGroup for MCP. Both register through M5 so the gate is the
same. Demo: `tern run "open hn, summarize top post"` and a fetch MCP
server work through one surface.
