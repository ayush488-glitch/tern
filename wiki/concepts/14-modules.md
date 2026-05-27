---
title: The 14 modules (M0–M14)
type: concept
created: 2026-05-27
updated: 2026-05-27
tags: [tern, architecture, modules]
---

# M0–M14 — what each module owns

Visual: see [architecture.html](../../docs/architecture.html).
Schedule: see [14-session-plan](../roadmap/14-session-plan.md).

| id | name | layer | owns | depends on | D? |
|---|---|---|---|---|---|
| M0 | CLI entry & bootstrap | L1 entry | composition root, arg parse, dependency wiring | nothing (only place that imports concrete adapters) | — |
| M1 | Agent turn loop | L2 core | async generator, perceive→reason→act→observe, max_steps, $ budget | M3, M4, M5, M11 | — |
| M2 | TUI · textual | L1 entry | reactive widgets, slash cmds, keybinds, --print mode | M14, M5 (render hooks) | — |
| M3 | Runtime shape | L2 core | WorkTask schema, sub-agent contract, stage descriptors | M4 (canonical types only) | — |
| M4 | Provider & cost router | L2 core | canonical messages, ProviderAdapter Protocol, per-turn model pick | nothing (adapters import provider SDKs) | **D1** |
| M5 | Tool surface & sandbox | L3 cap | uniform Tool Protocol, double-gated permissions, flags | M3 (canonical types only) | — |
| M6 | Skills runtime | L3 cap | SKILL.md loader, retrieval, scoped tool view | M5 (registry interface only) | **D2** |
| M7 | Session, replay, branch | L4 state | object store, refs, branches, JSONL transcripts | M4 (canonical only) | **D3** |
| M8 | Live HTML notes | L4 state | notes_append tool, notes_render hook, docs/notes.html | M7, M13 (redaction) | **D4** |
| M9 | Browser tool | L3 cap | browser-use BrowserSession, ToolResult mapping | M5 | **D5** |
| M10 | MCP client | L3 cap | ClientSessionGroup, transports, OAuth | M5 (registers into) | **D6** |
| M11 | Observability | L4 state | trace tree, spans, NDJSON, cost-per-span | nothing | — |
| M12 | Reliability | L5 cross | timeouts, breakers, atomic edits, journal | wraps M5, M4, M10 | — |
| M13 | Security | L5 cross | provenance, redaction, gate, audit log | wraps M5 writes | — |
| M14 | Slash commands & keybinds | L1 entry | declarative registries, three command modes | M2 | — |

## Layer rules
- L1 (entry) imports L2/L3/L4. Nothing imports L1.
- L2 (core) imports nothing concrete. M3 imports M4 canonical types only. M1 wires through.
- L3 (capabilities) imports L2 protocols. Never the other way.
- L4 (state) imports L2 canonical types. Never logic.
- L5 (cross-cutting) wraps via decorators / middleware. Doesn't sit in the import graph as a dep.

## The dependency direction
**All arrows point inward toward canonical types and the agent core.** That's the lock from [canonical-message-log](canonical-message-log.md) projected onto the import graph.

## Build order (from 14-session-plan)
M11 → M4 → M1+M0 → M5+M2 → M7 → M6+M8 → M9+M10 → M12+M13 → M14.

## Things this design forbids
- Global state in core. Pass session, store, adapter explicitly.
- BaseProviderAdapter with shared logic. Siblings, not subclasses.
- Skills hardcoded into core. Disk-discovered at runtime; never imported.
- LLM-generated commit messages. Deterministic `tern: <tool> on <files> · turn <id>`.
- Observability as afterthought. M11 ships in Phase 1, not last.
