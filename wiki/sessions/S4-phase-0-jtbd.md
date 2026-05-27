---
title: S4 — Phase 0, JTBD + scope (ADR-0001)
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [tern, session, phase-0, adr, jtbd]
---

# S4 — Phase 0: JTBD + scope

Filed [ADR-0001 jtbd-and-scope](../decisions/adr-0001-jtbd-and-scope.md). The anchor every future ADR cites.

## Decisions captured

| dimension | answer |
|---|---|
| primary user | open-source contributors, public from commit 1 of OS push |
| primary job | investigate + edit + browse + MCP, all in terminal |
| interface | textual TUI (no Electron, no web UI, no IDE plugin) |
| cost posture | no hard $ cap; quality first, D1 routes downward when provably cheap-suitable |
| autonomy | synchronous turns with approval gate; NOT overnight autonomous |
| distribution | `pipx install tern`; user-machine runtime; not a hosted SaaS |
| trust model | keys on user's machine; no cloud auth; no telemetry by default |

## Anti-scope (locked)
- Not autonomous overnight agent.
- Not a hosted SaaS / cloud product.
- Not a chatbot (output is edits/commits/actions, not conversation).
- Not an IDE plugin (no VS Code / JetBrains / Vim integration in v1).
- Not free-tier-or-bust (no artificial gating of premium models).
- Not vendor-locked (M4's canonical log makes provider-swap a per-turn decision).
- Not a small-model agent (frontier reasoning at the planner tier is the default).

## Success criteria — week 1 / 2 / 4
- **Week 1**: ADRs 0001–0005 filed, public-ready skeleton, README links to wiki.
- **Week 2**: M11 + M4 + M1 + M0 ship one-shot Bedrock turn with spans.
- **Week 4**: M5+M2 slice: interactive `tern` session, two tools (read_file, edit_block), permission prompt, end-to-end edit-with-approval-and-commit. **First "this is real" moment.**

## Five alternatives explicitly rejected
A. "Build for me first, open-source later" — README/contributor-docs lag.
B. "Edit-only first, browse+MCP later" — fragments M5's Tool Protocol.
C. "Web/GUI for accessibility" — breaks trust model; introduces SaaS surface.
D. "Hard $ cap per session" — pushes D1 into degraded mode by default.
E. "Autonomous overnight runs" — sandboxing maturity not there yet.

## Open questions deferred
- Telemetry / opt-in usage analytics (decide before public push; default off).
- `tern doctor` self-diagnostic (probably M14 polish, S15).
- Plugin marketplace shape (skills + MCP suffice for v1; registry post-v1).

## Handoff to S5
S5 = Phase 1 architecture sub-picks. Four ADRs:
- **ADR-0002 runtime-shape** — turn loop, async generator, state-replaced, max_steps, $ budget, reflection retry loop.
- **ADR-0003 tool-surface** — Tool Protocol, sandbox, double-gated permissions, flags, native + browser-use + MCP unification.
- **ADR-0004 provider-layer** — canonical messages, ProviderAdapter Protocol, Bedrock-first adapter, cost router policy v0 (D1).
- **ADR-0005 session-state** — object store, refs, branches, JSONL transcripts, replay/branch semantics (D3).

After S5 the design is locked end-to-end. S6 (M11 observability) starts implementation cleanly.

Gates green before starting S5: `pytest -q && ruff check src tests && mypy src` from `/Users/ayushsingh/Desktop/coding-agent/` with `.venv` activated.
