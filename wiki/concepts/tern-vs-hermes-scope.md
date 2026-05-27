---
title: Tern vs Hermes — scope decision
type: concept
created: 2026-05-28
updated: 2026-05-28
sources: []
tags: [tern, scope, hermes, roadmap, decision]
---

# Tern vs Hermes — scope decision

## What this page is
A record of the moment we decided Tern would grow beyond "focused coding agent"
toward Hermes-shaped breadth, and why nothing in S3–S14 had to change for that
to be a small lift.

## Context
At the end of S14 (commit a0b7571), Tern was a working CLI coding agent with
the six baked-in differentiators (D1–D6) plus production-grade reliability and
redaction. 210/210 tests green. Live Bedrock smoke clean.

Then Ayush asked the honest question: *"does tern have all the capability?"*
Compared to Hermes (his other agent — the general-purpose CLI platform), Tern
was missing twelve things: persistent memory across sessions, skill
self-creation, multi-model adapters (only Bedrock-Anthropic shipped), real
search engine integration, image input + screenshot, browser navigate/click/type
(only `web_fetch` shipped), self-curation, and a few smaller surfaces.

## The decision
Add a 5-session ladder (S15–S19) for breadth, push the original M14 polish +
walkthrough into S20, and call the original 14-session plan extended rather
than replaced. The ordering inside the ladder follows demo-visibility
([demo-visibility-first](../entities/ayush-singh.md) in user profile):

  S15 — memory + skills (Tern remembers you across sessions)
  S16 — model breadth (you can pick Nova for cheap classification)
  S17 — vision (Tern can see your screen)
  S18 — search + browser navigate (Tern can use the web like a human)
  S19 — self-curation (Tern grooms its own skills/memory)
  S20 — polish + pipx + walkthrough

Each session ends green, additive only. Reorder, don't remove.

## Why the foundation already supported this
Three S5 ADRs did most of the work:

- **ADR-0003 Tool Protocol + double-gated permissions** — every new tool
  (`memory`, `skill_manage`, `screenshot`, `web_search`, `browser_*`) drops in
  as one Tool subclass + one args model + one registry entry. Permission gating
  is uniform.
- **ADR-0004 canonical messages + provider-agnostic adapter** — every new
  model (openai, nova, kimi, xai) is one new file under `src/tern/adapters/`.
  Canonical layer doesn't move. ImageBlock already exists from S7 — vision is
  a wiring exercise, not a redesign.
- **ADR-0006 skills runtime** — already shape-compatible with Hermes pattern
  (`SKILL.md` + frontmatter + project-wins). `skill_manage` only adds CRUD
  on top of an existing loader.

The result: ~12 user-facing capabilities lift for ~10 hours of focused work.

## Notes on the notes_append bug
While diagnosing S15 prerequisites, found that `notes_append` was failing in
real chat runs. Symptom: HTML transcript present, "notes" section empty.
Root cause: the model (Sonnet 4) emitted literal text
`<notes_append>note text</notes_append>` as `llm_text_delta` events instead of
a structured `tool_use` block. The loop never saw a `ToolCallBlock`, so the
JSONL row was never appended. Transcript looked fine because the pseudo-XML
became part of the assistant message body.

Fix slated for S15: tighten the tool description to forbid pseudo-XML calls
and add a fallback canonical-layer parser that lifts a top-level
`<notes_append>...</notes_append>` text-block into a synthetic ToolCallBlock,
best-effort and idempotent. The JSONL store stays the single source of truth
for `notes_render` — the renderer doesn't need to change.

This is also a model-side observation worth keeping ([token-cost-master
pitfalls](../sources/token-cost-master.md) — Sonnet has been flaky on
disciplined tool-use lately. Belongs in MEMORY when S15 ships.

## Cross-refs
- [14-session plan](../roadmap/14-session-plan.md) — the extended ladder
- [adr-0003 tool surface](../decisions/adr-0003-tool-surface.md)
- [adr-0004 provider layer](../decisions/adr-0004-provider-layer.md)
- [adr-0006 skills runtime](../decisions/adr-0006-skills-runtime.md)
- [adr-0007 notes artifact](../decisions/adr-0007-notes-artifact.md)
