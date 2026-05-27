---
title: S5 — Phase 1, four architecture ADRs
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [tern, session, phase-1, adr, architecture]
---

# S5 — Phase 1: architecture sub-picks (4 ADRs)

Filed [ADR-0002 runtime-shape](../decisions/adr-0002-runtime-shape.md), [ADR-0003 tool-surface](../decisions/adr-0003-tool-surface.md), [ADR-0004 provider-layer](../decisions/adr-0004-provider-layer.md), [ADR-0005 session-state](../decisions/adr-0005-session-state.md). Design is locked end-to-end. Stage II (implementation) starts cleanly at S6.

## What got decided — five-bullet summary

| ADR | The lock |
|---|---|
| 0002 runtime-shape | Turn = `AsyncIterator[TurnEvent]`. `TurnState` frozen, replaced not mutated. Multi-source termination, ranked. Reflection retry as event with cap=3. Sub-agent contract sits at M5, not M1. |
| 0003 tool-surface | One `Tool` Protocol, three siblings (Native / Browser / MCP — never base class). Pydantic-derived JSON schemas. **Double-gated permissions**: registry filter + call-site enforce, both required. Modes: `--safe / --default / --yolo`. No Docker sandbox v1. |
| 0004 provider-layer | `CanonicalMessage` frozen+hashable. `ProviderAdapter` Protocol with pure `to_wire/from_wire`. v0 adapter = `bedrock_anthropic.py`. D1 cost router v0 = `FrontierFirstPolicy` (rule-based, frontier default). litellm = ONE backend, NOT THE abstraction. |
| 0005 session-state | `~/.tern/projects/<cwd>/{objects, refs, sessions/*.jsonl, index.sqlite}`. Turn-object content-addressed (sha256). Sessions = chains; branches = forks; replay = walk parents, re-feed canonical (pure / live / cross-model). Conversation branching ≠ filesystem branching. |

## Architectural invariants now committed in writing
1. Internal canonical message log ≠ provider wire format. (ADR-0004 cashing the lock from `concepts/canonical-message-log.md`.)
2. State is replaced, never mutated. (ADR-0002.)
3. One tool surface across native + browser + MCP. (ADR-0003.)
4. Cost-routing is per-turn, frontier-first, downgrade only when provably cheap. (ADR-0004.)
5. Every turn is a content-addressed object; the past is immutable; branches are refs. (ADR-0005.)
6. Sub-agents are tool calls. (ADR-0002 + ADR-0003.)
7. The user owns the bill; the runtime owns honesty. (ADR-0001 + ADR-0004.)

## Forbidden patterns (cite these to refuse drift)
- ❌ `BaseProviderAdapter` / `BaseTool` abstract class with shared logic. Sibling implementations only.
- ❌ Mutable session state. Frozen dataclasses + structural sharing.
- ❌ Mutating turn-objects. Rewrite = new object, same parent, new hash.
- ❌ Storing Anthropic-shaped (or any provider-shaped) messages. Canonical only.
- ❌ Single permission gate. Both filter AND enforce, or neither counts.
- ❌ Hard `$/session` cap. Cost is reported, not enforced.
- ❌ litellm as THE abstraction. It's a fallback adapter; first-party SDK adapters preferred.
- ❌ Filesystem-state inside turn-objects. Git is git's job.
- ❌ LLM-generated commit messages. Deterministic `tern: <tool> on <files> · turn <hash>`.
- ❌ Pickle. Stable JSON only (`sort_keys=True, separators=(",",":")`).

## What's pre-loaded for S6
S6 implements **M11 observability skeleton** — first module to land. Why first: can't debug or cost-route without it.

ADR-0002 already specified the event vocabulary M11 listens to:
`LLMRequested · LLMResponded · ToolCalled · ToolReturned · ApprovalRequested · ApprovalGranted · ReflectionTriggered · TurnCompleted · UserAborted`.

S6 deliverables:
- `src/tern/obs/` — span tree, NDJSON sink, cost-per-span aggregation.
- `~/.tern/projects/<cwd>/spans/<session>.ndjson` — append-only span log.
- `tern spans <session>` — pretty-print span tree (rich.tree.Tree).
- Tests: a fake turn yielding 5 mock events produces the expected span tree shape.

S6 has NO LLM dependency. Tests use `FakeAdapter` from S7-prep. M11 lands first specifically so S7's adapter ships with observability already wired.

## Open questions logged for later
- Streaming token-level events through canonical (ADR-0004 §open) — TUI polish, S15.
- Mid-turn provider swap (D1 routing changes between steps) — v1.1.
- Concurrent tool calls (parallel ToolCalled events) — schema supports, scheduler doesn't, v1.1.
- Allowlist file `.tern/allowlist.toml` for path/command pre-approval (ADR-0003 §open) — post-v1.
- `tern gc` for orphaned turn-objects (ADR-0005 §open) — post-v1.
- Cross-machine session sync (ADR-0005 §open) — out of scope.
- Telemetry / opt-in usage analytics (ADR-0001 §open) — decide before public push.

## Handoff
Gates green: `pytest -q && ruff check src tests && mypy src` from project root with `.venv` activated.

Next session = S6: M11 observability skeleton. Read `AGENTS.md`, `wiki/index.md`, `wiki/roadmap/14-session-plan.md` (▶ S6), this S5 page, then `wiki/decisions/adr-0002-runtime-shape.md` (defines the event vocabulary M11 listens to).
