---
title: claude-code (TS clone)
type: entity
created: 2026-05-27
updated: 2026-05-27
sources: [../sources/ref-claude-code.md]
tags: [reference, typescript, coding-agent]
---

# claude-code

TS clone of Anthropic's Claude Code. ~2200 files. Cloned for design DNA, not direct lift (we're Python).

Repo (cloned, gitignored): `.scratch/grounding/refs/claude-code`.

## What we lift
- **Turn-loop async generator** with `state-replaced` (not mutated) at every continue site.
- **Double-gated permissions**: filter at registry, enforce at call site.
- **JSONL transcripts** at `~/.tern/projects/<sanitized-cwd>/<uuid>.jsonl` (renamed from `~/.claude`).
- **Deterministic cache breakpoints** in prompt construction.

## What we adapt
- Tool Protocol → Pydantic dataclasses (TS uses Zod).
- ink + yoga + React → textual (Python-native reactive widget tree).

## What we skip
- bun:bundle `feature()` macro — replace with runtime plugins + skills (M6). Disk-discovered, not compiled in.

See [sources/ref-claude-code.md](../sources/ref-claude-code.md) for the full extraction.
