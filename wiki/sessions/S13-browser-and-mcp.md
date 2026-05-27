---
title: S13 — browser-shaped tool slot + MCP client
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [s13, d5, d6, browser, mcp]
---

# S13 — browser-shaped tool slot (D5) + MCP client (D6)

## Built (~75 min)

- `src/tern/tools/native/web_fetch.py` — `WebFetchTool` v0. urllib + stdlib HTML
  stripper. `read_only=True, open_world=True`. 32 KiB cap, http/https only.
- `src/tern/tools/mcp/__init__.py` — full MCP bridge:
  - `MCPServerConfig` dataclass, `load_mcp_config(cwd)` reads
    `.tern/mcp.json` (project) or `~/.tern/mcp.json` (user, project shadows)
  - `MCPManager` async context manager — owns one `AsyncExitStack`,
    spawns each stdio server, opens `ClientSession`, lists tools
  - `_make_bridge` wraps each remote tool as `MCPBridgedTool` (Tool Protocol
    conformant — gate sees it like everything else)
  - `_bridge_result` maps `CallToolResult` → `ToolResult` (text parts joined,
    artifact count in metadata, `isError` → `ok=False`)
  - per-server failures non-fatal — log + skip
- `src/tern/cli.py` — `tern run` now wires `Registry([Read, Edit, Notes, WebFetch])`
  + `PermissionGate()`, then under one `asyncio.run` opens `MCPManager.connect`
  for the turn, registers bridged tools, runs the loop. Prints
  `mcp: N tool(s) bridged` to stderr when servers load.
- `src/tern/ui/app.py` — `WebFetchTool` added to the chat REPL registry.
  (MCP for chat REPL deferred — see follow-up.)
- `tests/test_web_fetch.py` — 9 tests (args validation, HTML stripping,
  truncation, network-error handling, annotations).
- `tests/test_mcp_bridge.py` — 12 tests (config loader, result mapping,
  bridge construction, invoke success + failure, default annotations).
- `tests/_mcp_echo_server.py` + `tests/test_mcp_integration.py` — spawns
  a real stdio MCP server (echo tool), bridges it, invokes it, verifies
  the response. Real subprocess, no mocks.
- `wiki/decisions/adr-0008-browser-and-mcp.md` — decision + alternatives.

## Demoable end-to-end

```
TERN_LIVE=1 tern run "fetch http://example.com and tell me the page heading in 5 words"

· us.anthropic.claude-sonnet-4-...  in=1169 out=57 $0.0000
· us.anthropic.claude-sonnet-4-...  in=1284 out=7 $0.0000
example domain documentation site
notes: ~/.tern/projects/.../0e5eeee249c1.html
session 0e5eeee249c1  ·  cost $0.0000
```

Spans confirm `tool_called: web_fetch` + `tool_returned`.

MCP integration test confirms a real `python tests/_mcp_echo_server.py`
subprocess loads, lists `echo`, returns `"echo: hi"` through the bridge.

## Gates

- pytest **159/159** ✅ (137 prior + 21 web_fetch/MCP-unit + 1 MCP-integration)
- ruff ✅
- mypy --strict ✅ (37 src files)

## Pitfalls caught

- **Ruff RUF012** on web_fetch's class-level tag sets — fixed with
  `ClassVar[frozenset[str]]`. Mutable class defaults in Python lint as
  bugs even when intent is "constant".
- **MCP SDK quirk**: `Tool.annotations` is sometimes `None` and sometimes
  a Pydantic model with `destructiveHint`/`idempotentHint`/`readOnlyHint`/
  `openWorldHint`. The bridge handles both; default annotations
  (idempotent=True, others False) when missing.
- **chat REPL MCP wiring**: each chat turn does its own `asyncio.run`,
  so the same `MCPManager` can't span turns without restructuring. Logged
  as follow-up; `tern run` (the demo path) wires MCP correctly.

## ADRs touched

- **ADR-0008** new — browser-shaped tool slot + MCP client.

## What's next (S14 candidate)

Per-roadmap, S13 was the final core-feature session. Next directions:
- **S14 — UX polish + docs**: chat REPL MCP, `--mode yolo`, demo gif,
  README that pitches the six diffs.
- **Real browser-use behind WebFetchTool**: Playwright + a stateful
  navigation tool. Same Tool name, swap implementation.
- **HTTP-transport MCP**: stdio is enough today; HTTP servers expand
  the ecosystem.
- **D1 cost router upgrade**: today routing is purpose → static map.
  Upgrade to per-turn cost-aware routing (M11).
