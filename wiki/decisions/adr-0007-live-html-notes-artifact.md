---
title: ADR-0007 — live HTML notes artifact (D4)
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [tern, d4, notes, html, artifact, observability]
---

# ADR-0007 — live HTML notes artifact (D4)

## Context
D4 promised a "live HTML notes artifact" — a single static file the agent
keeps fresh as a session progresses, suitable for sharing, printing, or
archiving without booting a server. S10 already gave us turn-objects (the
record of what was said). The artifact needs two things turn-objects alone
don't carry:

1. Free-form annotation. Sometimes the agent decides "this is worth flagging
   for a future reader" — a decision, a pitfall hit, a TODO surfaced. That's
   a note, not a turn.
2. A presentation layer. Replay can rebuild messages, but a CLI dev wants to
   open a tab, scroll, ⌘P to PDF, drop the file into docs/.

We also want the artifact to refresh **per turn** (live), not on demand. If
the user kills the process mid-conversation, the last good HTML stays on
disk.

## Decision
Add a **note store** alongside the turn-object store, and a **server-side
HTML renderer** invoked as a per-turn hook.

**Storage** (mirrors ADR-0005 layout):
```
~/.tern/projects/<sanitized-cwd>/notes/<session_id>.jsonl   (rows, append-only)
~/.tern/projects/<sanitized-cwd>/notes/<session_id>.html    (rendered artifact)
```

JSONL row shape: `{ts, turn_idx, kind, text, tags}`. Append is naturally
atomic on POSIX for short writes (we open with `O_APPEND`); reads tolerate
a partial trailing line so a process killed mid-write doesn't poison the
store.

**Tool surface** (per ADR-0003 §native): a `notes_append` tool. The model
can call it just like `read_file`. It's classified non-destructive (writes
go to `~/.tern`, not the repo) — no approval prompt in default mode. The
tool stamps the row with `ctx.session_id` + `ctx.turn_idx` so notes
interleave correctly in the artifact even if the model fills in nothing.

**Renderer**: `tern.notes.render.render_html(session_id, cwd, out_path)`.
Reads the chain via `walk_chain(read_session_head(...))`, reads notes via
`read_notes(...)`, emits one self-contained HTML file (CSS inline, zero
JS, zero external assets). Same b&w / serif-display aesthetic as
`docs/architecture.html`. Three sections: summary KPIs, notes list,
transcript with role-tagged turn cards.

**Hook**: chat REPL and `tern run` both call `render_html(...)` once after
the turn persists. Best-effort — render failure logs but doesn't break the
loop. The notes file lives at `<project_dir>/notes/<session>.html` by
default; `tern notes [session] --out path/to.html` overrides for a manual
render.

## Alternatives considered

A. **JSON sidecar + client-side renderer**. Tempting (ship JSON, let a
   dashboard render it). Rejected: pulls a server-side dependency or
   forces a JS bundle into the artifact. The whole point is a static file
   that survives airgap.

B. **Mutate `docs/notes.html` in the repo**. Considered. Rejected:
   pollutes git status on every turn; users running `tern run` in a clean
   repo don't expect the agent to touch their tree without a tool gate. The
   project_dir under `~/.tern/` keeps it side-effect-free, and `tern notes
   --out` opts users in when they want it in-tree.

C. **Stream incrementally as turns happen** (write a `<turn>` block each
   event). Rejected for now: full re-render is cheap (one session = a few
   KB of HTML); incremental writes complicate the structure with no win.
   Revisit if sessions grow to hundreds of turns.

D. **Templating engine (Jinja, etc.)**. Rejected: one template doesn't
   justify a dep. Raw f-strings are auditable and ship today.

## Consequences

- One new package: `src/tern/notes/` (store + render).
- One new tool: `notes_append` registered in chat REPL's registry. (`tern
  run` is currently tool-less; render hook still fires for the artifact.)
- New CLI command: `tern notes [session]`, with `--out`, `--open`.
- Notes are NOT included in turn-object hashes — they're orthogonal data.
  This is deliberate: a note row added late doesn't invalidate replay.
- HTML is escaped at render time (`html.escape`) on every model-controlled
  string; one test pins this against a `<script>` injection.
- The artifact regenerates from authoritative state every time, so
  truncating notes / rewinding turns produces a correct file with no stale
  fragments left behind.

## Verified
- 12 new tests in `tests/test_notes.py` (137 total green).
- `mypy --strict` clean (35 src files).
- Live Bedrock: `tern run` writes the artifact and prints its path. File
  inspected: contains masthead, summary KPIs, transcript with both user
  and assistant blocks.

## Pointers
- `src/tern/notes/store.py` — `Note`, `append_note`, `read_notes`.
- `src/tern/notes/render.py` — `render_html`, inline CSS.
- `src/tern/tools/native/notes_append.py` — model-callable tool.
- Render hook: `src/tern/cli.py::run` + `src/tern/ui/app.py::run_chat`.
- CLI: `tern notes` in `src/tern/cli.py`.
