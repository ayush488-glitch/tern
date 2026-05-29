---
title: session plan (S3 → S20)
type: roadmap
created: 2026-05-27
updated: 2026-05-27
tags: [tern, roadmap, sessions]
---

# Tern — 14-session plan

The full ladder from "design grounded" → "v1 shipped" → "walkthrough published".
Every session ends green: tests pass, CLI runs, commit made.
Each session captures `wiki/sessions/SNN-<topic>.md` while it's fresh.

---

## Status

| | session | status | when |
|---|---|---|---|
| | S1 grounding decisions | ✅ done | 2026-05-27 |
| | S2 grounding execution + architecture.html | ✅ done | 2026-05-27 |
| | S3 repo skeleton + first green commit | ✅ done | 2026-05-27 |
| | S4 Phase 0 — JTBD + scope (ADR-0001) | ✅ done | 2026-05-27 |
| | S5 Phase 1 — architecture sub-picks (4 ADRs) | ✅ done | 2026-05-27 |
| | S6 M11 observability skeleton | ✅ done | 2026-05-27 |
| | S7 M4 canonical messages + first adapter | ✅ done | 2026-05-27 |
| | S8 M1 + M0 turn loop + CLI (one-shot Bedrock) | ✅ done | 2026-05-27 |
| | S9 M5 + M2 slice (two tools + textual TUI) — 🎉 demo-visible | ✅ done | 2026-05-27 |
| | S9.5 inline REPL (rip Textual) + day-1 streaming + diff-up-front | ✅ done | 2026-05-27 |
| | S10 M7 session, replay, branch (D3) | ✅ done | 2026-05-28 |
| | S11 M6 skills runtime (D2) | ✅ done | 2026-05-28 |
| | S12 M8 live HTML notes artifact (D4) | ✅ done | 2026-05-28 |
| | S13 M9 + M10 browser + MCP (D5 + D6) | ✅ done | 2026-05-28 |
| | S14 M12 + M13 reliability + security + tool parity | ✅ done | 2026-05-28 |
| | S15 persistent memory + skill self-mgmt + notes-fix | ✅ done | 2026-05-28 |
| | S16 model breadth (nova, openai) + cost router populated | ✅ done | 2026-05-28 |
| | S17 repo-scoped memory tier (Layer A — ADR-0011 substrate) | ✅ done | 2026-05-28 |
| | S18 cognitive router + KNN recall (ADR-0011 subsystems 1+2) | ✅ done | 2026-05-29 |
| | S19 curator subsystem (ADR-0011 subsystem 3) | ✅ done | 2026-05-29 |
| | S20 StackOverflow error lookup (ADR-0011 subsystem 4) | ✅ done | 2026-05-29 |
| | S21 long-running build hardening (ADR-0012) | ✅ done | 2026-05-29 |
| | S22 vision: ImageBlock + screenshot tool | ✅ done | 2026-05-29 |
| **▶** | **S23 — next per ADR-0011 / roadmap** | **next** | — |
| | S23 real search + browser navigate/click/type | — | — |
| | S24 M14 polish + pipx + walkthrough | — | — |

**Sequencing is locked by ADR-0011 + ADR-0012.** The table above supersedes the
original plan. S17→S20 are the moat (cognitive routing + memory + curation). S21
is long-running build hardening. S22–S24 are vision, browser, and ship.
Sources: [adr-0011](../decisions/adr-0011-cognitive-routing-and-recall.md),
[adr-0012](../decisions/adr-0012-long-running-build-hardening.md).

---

## Stage I — DESIGN-LOCK (S3–S5)
Goal: every architectural decision written down before any production code.

### S3 · repo skeleton + first green commit (~20 min)
- `pyproject.toml` (uv-friendly), `src/tern/`, `tests/`, ruff + mypy + pytest configured
- `tern --version` prints version
- `pytest` green
- First commit: "init: empty tern skeleton, green"
- Walkthrough Ch1 will lift from this state

### S4 · Phase 0 — JTBD + scope (~30 min)
File: `wiki/decisions/adr-0001-jtbd-and-scope.md`
- who is this for, what job, success criteria
- what it isn't, anti-scope
- demo-visibility milestones (week 1 / 2 / 4)

### S5 · Phase 1 — architecture sub-picks (~60 min, 4 ADRs)
- `adr-0002-runtime-shape.md` — turn loop, async generator, state-replaced
- `adr-0003-tool-surface.md` — tool protocol + sandbox + permission engine
- `adr-0004-provider-layer.md` — canonical messages + cost router (D1)
- `adr-0005-session-state.md` — object store + refs + branches (D3)

---

## Stage II — MINIMAL VIABLE AGENT (S6–S9)
Goal: end-to-end one-shot turn against Bedrock, observable, with two tools.

### S6 · M11 observability skeleton (~45 min)
Spans, NDJSON logger, trace tree, cost-per-span. Tests prove a fake turn emits the right span shape.
**Why first**: can't debug or cost-route without it.

### S7 · M4 canonical messages + first adapter (~90 min)
`CanonicalMessage` / `ContentBlock` / `ToolSpec` dataclasses. `ProviderAdapter` Protocol. One Bedrock-Anthropic adapter. Cost router stub (single policy). Roundtrip tests with FakeAdapter.

### S8 · M1 + M0 turn loop + CLI (~90 min)
`tern run "say hello"` → real Bedrock call → printed reply. No tools yet. Loop terminates after one turn. Spans flow to M11.

### S9 · M5 (slice) + M2 (slice) — two tools + TUI (~120 min)
Tools: `read_file`, `edit_block` (search/replace lifted from aider). Textual TUI, slash commands `/exit /model /status`. Permission prompt for `edit_block`. Reflection loop on parse errors.
**🎉 End of S9: working coding agent. Demo-visible.**

---

## Stage III — DIFFERENTIATORS (S10–S13)
Goal: the six things nobody else has, layered onto a working base.

### S10 · M7 session, replay, branch (D3) (~120 min)
Object store + refs + JSONL transcripts. `tern log`, `tern resume`, `tern branch`. Replay = walk parents, re-feed, assert hash. **Must come before S11/S12** (notes regen reads turn objects).

### S11 · M6 skills runtime (D2) (~75 min)
SKILL.md loader. Disk-discovered at startup. Retrieval-shaped per turn (start dumb: keyword match). Scoped tool view. Routes to wikis.

### S12 · M8 live HTML notes artifact (D4) (~75 min)
`notes_append` tool + `notes_render` hook. Reads turn objects from M7. Writes `docs/notes.html` each turn. Same b&w aesthetic as `architecture.html`.

### S13 · M9 + M10 browser + MCP (D5 + D6) (~120 min)
browser-use as one tool. ClientSessionGroup for MCP. Both register into M5. Demo: `tern run "open hn, summarize top post"` and a fetch MCP server work through the same surface.

---

## Stage IV — HARDENING + SHIP (S14–S16)
Goal: stable enough for `pipx install tern` and a public README.

### S14 · M12 + M13 reliability + security pass (~90 min) ✅ done 2026-05-28
Shipped: 4 core-loop tools (write_file, glob, grep, bash) behind ADR-0003 protocol;
sink-level secret redaction (ADR-0010) with stable per-session placeholders;
Bedrock full-jitter retry/backoff on throttle/5xx/timeout. 210/210 tests green.
ADRs: 0009 (tool parity), 0010 (redaction).

---

## Stage V — HERMES-SHAPED BREADTH (S15–S19)
Goal: lift Tern from "focused coding agent" to a general-purpose CLI agent.
Each session is additive; nothing in S3–S14 changes shape.

### S15 · persistent memory + skill self-mgmt + notes-fix (~120 min)
- **Memory** — Hermes-style split: `~/.tern/memory/MEMORY.md` (procedural notes,
  ~2.2KB cap) + `~/.tern/memory/USER.md` (identity/preferences, ~1.4KB cap).
  Loaded once per session, injected into the system prompt under
  `══ MEMORY ══` / `══ USER PROFILE ══` banners, same shape as Hermes.
  New tool `memory` with actions `add | replace | remove`, target `memory|user`,
  per ADR-0003 protocol.
- **`skill_manage` tool** — actions `create | patch | edit | delete |
  write_file | remove_file`. Same surface Hermes uses, scoped to
  `~/.tern/skills/<name>/SKILL.md` and `.tern/skills/...` (project wins).
  Auto-skill-creation reflection hook lives behind a `--reflect-skills` flag,
  off by default.
- **`notes_append` fix** — root cause: model emits literal `<notes_append>...
  </notes_append>` text instead of a tool_use block, so loop never fires.
  Two-part fix: (a) tighten the tool's `description` to forbid pseudo-XML
  and require structured tool-use; (b) add a fallback parser at the canonical
  layer that lifts a top-level `<notes_append>text</notes_append>` text-block
  into a synthetic ToolCallBlock (best-effort, idempotent). Either path lands
  the JSONL row, which is the single source of truth `notes_render` reads.
- **Self-curation v0** — append a one-liner to `MEMORY.md` after a successful
  difficult turn (gated). Wires the loop that S19 expands into `tern curate`.

### S16 · model breadth + cost router populated (~120 min)
- New adapters under `src/tern/adapters/`: one file each for `openai`,
  `bedrock_nova`, `bedrock_kimi`, optional `xai`. Per ADR-0004, a new model
  is one new file; canonical layer doesn't change.
- D1 cost router populated with real per-model `$/1M tok` numbers (lift from
  `references/bedrock-models-ayush.md` + token-cost-master).
- `tern config set default_model <id>` + `--model` per-turn override.
- Pitfall: Kimi K2.5 on Bedrock needs OpenAI-style `{"type":"function",
  "function":{...}}` tool wrapper (see token-cost-master pitfalls). Add a
  per-model serializer in the bedrock_kimi adapter.

### S17 · vision (image input + screenshot tool) (~90 min)
- `ImageBlock` already exists in canonical (S7) — wire it through the
  Bedrock-Anthropic adapter (base64 + media_type). Same plumbing for OpenAI.
- New `screenshot` tool: macOS `screencapture -x -t png /tmp/...`,
  Linux `gnome-screenshot|grim`. Returns an ImageBlock. Gated `destructive=False,
  read_only=True`.
- `tern run "what's on my screen"` works end-to-end on a vision-capable model.

### S18 · real search + browser navigate/click/type (~150 min)
- `web_search` tool — Tavily first (one HTTP call, returns markdown), Brave
  optional. Key lives in `~/.tern/config.yaml` under `search.tavily_api_key`.
- Promote `web_fetch` (S13) to a Playwright-backed `web_fetch` swap behind the
  same name (ADR-0008 promised this). Caches in `~/.tern/cache/web/`.
- New tools: `browser_navigate`, `browser_click`, `browser_type`,
  `browser_snapshot`, `browser_vision` — all driving one persistent
  Playwright context. Permission-gated: navigate/snapshot=non-destructive,
  click/type=destructive (approval prompt).

### S19 · self-curation `tern curate` (~75 min)
- Standalone CLI command + scheduled-on-demand pass: review skills for
  staleness (ctime > N days, no recent reads), prune memory entries >30 days
  old that haven't been re-read, surface candidates the user approves before
  delete. Same shape as Hermes curator.
- Adds `last_used_at` to skill frontmatter on every load (S11 hook).

---

## Stage VI — POLISH + SHIP (S20)

### S20 · M14 polish + pipx + walkthrough (~120 min)
- Slash commands + keybindings registries. `--print` mode.
- `pipx install tern` smoke test on a clean machine.
- Assemble `.scratch/walkthrough-notes/chNN-*.md` (captured during S6–S19)
  into the teaching repo. Same audience/contract as ai-native-swe-walkthrough.

---

## Demo-visibility checkpoints
- **S9** — working coding agent (interactive, two tools, real Bedrock)
- **S13** — full feature surface (replay, skills, notes, browser, MCP)
- **S14** — production-grade (tool parity + redaction + retry)
- **S15** — Tern remembers you across sessions
- **S17** — Tern can see
- **S18** — Tern can browse the web like a human
- **S20** — installable + teachable

## Calendar shape
20 sessions × ~80 min average ≈ 27 focused hours. Realistically 5–8 weeks calendar time.

## Reorder, don't remove
This plan stays additive. If a session needs to swap places with another, reshuffle. Don't drop scope.
