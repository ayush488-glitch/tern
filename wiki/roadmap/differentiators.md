---
title: Six differentiators (D1–D6)
type: roadmap
created: 2026-05-27
updated: 2026-05-27
tags: [tern, differentiators]
---

# D1–D6 — what makes Tern not just another Claude Code clone

Six things baked into v1 architecture (not retrofitted). No shipping coding agent has all six.

| ID | Name | Lives in | Status |
|---|---|---|---|
| D1 | Per-turn cost routing | M4 (provider + router) | architected, S7 ships stub |
| D2 | Skills as first-class | M6 (skills runtime) | architected, S11 ships |
| D3 | Per-turn replay + branch | M7 (session/state) | architected, S10 ships |
| D4 | Live HTML notes artifact | M8 (notes) | architected, S12 ships |
| D5 | Browser-use as real tool | M9 (browser tool) | architected, S13 ships |
| D6 | MCP client built-in | M10 (MCP client) | architected, S13 ships |

## D1 — per-turn cost routing
Every turn picks its own model from a policy. Plan with Haiku, edit with Sonnet, debug with Opus. Same canonical messages, different adapter.
**Why others don't have it**: requires canonical message log decoupled from provider wire format. Tool-schema shapes differ (Anthropic bare vs OpenAI `{type:"function",function:{}}`), conversation-state portability is hard, vendor lock-in disincentivizes the work.

## D2 — skills as first-class
SKILL.md loaded like tools, scoped per turn, retrieval-shaped. System prompt stays thin; expertise composable on disk.

## D3 — per-turn replay + branch
Every turn is a content-addressed object. Git for agent sessions: walk, fork, A/B prompts, resume after crash by replay.

## D4 — live HTML notes artifact
A b&w HTML implementation note rendered at runtime, not just teaching-time. The agent works and the artifact updates.

## D5 — browser-use as real tool
Long-lived BrowserSession per Tern session. `agent.run()` once per call, surface AgentHistoryList → ToolResult. Sub-agent contract.

## D6 — MCP client built-in
ClientSessionGroup. stdio/http/sse. Remote tools register into M5 with namespace prefix and same permission gate as native tools.

---
See [14-session-plan](14-session-plan.md) for when each lands.
See [architecture.html](../../docs/architecture.html) for the visual.
