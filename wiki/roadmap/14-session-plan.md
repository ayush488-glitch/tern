---
title: 14-session plan (S3 → S16)
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
| **▶** | **S10 M7 session, replay, branch (D3)** | **next** | — |
| | S11 M6 skills runtime (D2) | — | — |
| | S12 M8 live HTML notes artifact (D4) | — | — |
| | S13 M9 + M10 browser + MCP (D5 + D6) | — | — |
| | S14 M12 + M13 reliability + security pass | — | — |
| | S15 M14 polish + global install | — | — |
| | S16 walkthrough authored from notes | — | — |

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

### S14 · M12 + M13 reliability + security pass (~90 min)
Timeouts, circuit breaker, atomic edits with journal. Provenance tagging. Entropy-aware redaction. Dangerous-action gate. Audit log of every write.

### S15 · M14 polish + global install (~60 min)
Slash commands + keybindings registries. `--print` mode. `pipx install tern` smoke test on a clean machine.

### S16 · walkthrough authored from notes (~120 min)
Assemble `.scratch/walkthrough-notes/chNN-*.md` (captured during S6–S15) into the teaching repo. Same audience/contract as ai-native-swe-walkthrough.

---

## Demo-visibility checkpoints
- **S9** — working coding agent (interactive, two tools, real Bedrock)
- **S13** — full feature surface (replay, skills, notes, browser, MCP)
- **S15** — installable
- **S16** — teachable

## Calendar shape
14 sessions × ~75 min average ≈ 17 focused hours. Realistically 3–6 weeks calendar time.

## Reorder, don't remove
This plan stays additive. If a session needs to swap places with another, reshuffle. Don't drop scope.
