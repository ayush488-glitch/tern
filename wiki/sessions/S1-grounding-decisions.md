---
title: S1 — grounding decisions (planning chat)
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [tern, session, grounding, planning]
---

# S1 — grounding decisions

The planning chat that produced Tern's foundational locks. Most was conversation; the on-disk artifact is mostly downstream of the decisions made here.

## What got decided

- **Repo layout**: A1 single repo at `/Users/ayushsingh/Desktop/coding-agent/`. Notes in `.scratch/`, wiki at `wiki/`, walkthrough subfolder added later.
- **Name**: started `antern`, finalized `tern` in S3. Open source; brand later.
- **Six differentiators baked into v1**: D1 per-turn cost routing, D2 skills first-class, D3 per-turn replay/branch, D4 live HTML notes artifact, D5 browser-use first-class, D6 MCP day-one. See [differentiators](../roadmap/differentiators.md).
- **Provider**: Bedrock first (existing creds), pluggable from day 1.
- **Walkthrough timing**: develop AFTER codebase. Notes captured `.scratch/walkthrough-notes/chNN-*.md` after each phase ends green. S16 assembles.
- **HTML architecture artifact**: pure b&w, monospace + serif, single SVG. Scales thumbnail → 4K. Tufte-meets-blueprint. Lives at `docs/architecture.html`.
- **Module map M0–M14**: accepted.

## The lock that came out of S1
**Internal canonical message log ≠ provider wire format.** Two pure functions translate. Everything else follows. See [canonical-message-log](../concepts/canonical-message-log.md).

## Why others don't do per-turn cost routing (D1)
- Tool-schema shapes diverge across vendors (Anthropic bare vs OpenAI wrapped).
- Conversation-state portability is hard (system prompts top-level vs messages[0], image blocks, caching).
- Vendor lock-in disincentivizes the work.
- Tern eats this complexity in M4's adapter layer so the agent core never sees it.

## Resolved questions (going into S2)
- Repo layout ✓ A1
- Name source ✓ Antern → finalized `tern`
- Clone references ✓ into `.scratch/grounding/refs/`
- HTML architecture artifact ✓ detailed, b&w, scalable
- Walkthrough timing ✓ end, notes-as-we-go
- v1 scope ✓ minimal viable, full system designed
- CLI ✓ rich, globally installable
- Audience ✓ same as ai-native-swe-walkthrough
- D1–D6 ✓ all in
- Wiki breadth ✓ beyond just llmops

## What S1 did NOT decide (deferred to S2+)
- Specific Phase 0 / Phase 1 ADR contents (S4, S5).
- Repo skeleton specifics (S3).
- Test framework choice details (pytest, but config TBD in S3).
