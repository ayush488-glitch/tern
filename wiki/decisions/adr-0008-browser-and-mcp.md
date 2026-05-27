---
title: ADR-0008 — browser-shaped tool slot + MCP client
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [d5, d6, browser, mcp, tools, s13]
---

# ADR-0008 — browser-shaped tool slot (D5) + MCP client (D6)

## Context

Two of the six baked-in differentiators (D5 browser-use, D6 MCP) are the
"open-world" tools — they let the agent reach beyond the repo. Both need to
land on the same Tool Protocol so the gate, the registry, and the adapter
treat them like everything else. Tools-of-tools, not tools-on-the-side.

Two pressures shaped S13:

1. **Time budget**. Real `browser-use` pulls Playwright + a Chromium
   download (~200 MB) and a non-trivial control loop. Putting that in the
   first cut would have eaten the whole session and given us a single tool
   we couldn't easily mock in tests.
2. **Surface symmetry**. D5 and D6 are both "open-world I/O" — they should
   look the same to the model. If we build a heavy browser tool first and
   bolt MCP on later, the surface drifts.

So we ship the **slot**, not the engine.

## Decision

### D5 — `web_fetch` v0 as the browser-shaped tool

A native `web_fetch` tool: takes a URL, fetches via `urllib`, strips HTML
to plain text, returns it. Annotations: `read_only=True`, `open_world=True`,
`destructive=False`. Permission gate sees it; the default-mode prompt asks
on first use only because of `open_world`.

Why `urllib` and not `httpx`/Playwright:
- stdlib only → zero new runtime deps, no Chromium binary
- enough for "fetch this page, summarize it" — the actual demo on the
  roadmap
- the seam is the tool *interface*, not the implementation. Swap in
  Playwright behind the same `WebFetchTool` later without touching the
  loop, the gate, or any adapter.

Limits:
- text-only (HTML stripped, scripts/styles dropped)
- 32 KiB cap on returned text (truncation flag in metadata)
- `http`/`https` only (`file://`, `ftp://` rejected at args validation)
- no JS execution, no clicking, no forms

That's S13's honest scope. Real browser-use ships behind the same tool
name in a future session.

### D6 — MCP client with stdio servers, bridged into the registry

Connect to MCP servers configured in `.tern/mcp.json` (project) or
`~/.tern/mcp.json` (user). For each server, list its tools and wrap each
remote tool as an `MCPBridgedTool` that conforms to the Tern Tool Protocol.

Config shape mirrors the Claude Desktop / `claude_code` convention so
servers carry over without rewrites:

```json
{
  "mcpServers": {
    "fetch":   { "command": "uvx", "args": ["mcp-server-fetch"] },
    "memory":  { "command": "node", "args": ["./mcp-memory-server.js"] }
  }
}
```

Lifecycle: an `MCPManager` async context manager owns one
`AsyncExitStack` that holds every `stdio_client` + `ClientSession`. Open
once per `tern run`, tools registered into the local Registry, closed on
turn end. Per-server failure is non-fatal — we log and skip that server,
the rest still load.

`MCPBridgedTool.invoke`:
- payload = the model's tool args dict (passed through verbatim — MCP
  servers own their own schema validation, we only assert "object")
- result content parts → joined text (text parts) + artifact count in
  metadata
- `isError=True` from the server → `ToolResult(ok=False, ...)`, never raises

Annotations are mapped from MCP `tool.annotations` (camelCase hints) to
Tern's `ToolAnnotations` (snake) so the gate can decide just like for
native tools. If a remote tool is `destructiveHint=True`, the gate prompts
in default mode; in YOLO mode it auto-approves. **The gate doesn't
distinguish remote from local — that's the point.**

## Alternatives

1. **Ship full browser-use this session.** Rejected: ~200 MB Chromium +
   a heavy control loop = no time for D6, demo blocked on a single tool.
2. **Skip the config file, hardcode one MCP server.** Rejected: the whole
   point of the MCP client is "you bring your servers", and the config
   shape needs to land before users build around it.
3. **Wrap the MCP session per-tool-call (open + close around each invoke).**
   Rejected: connection cost dominates, and most servers expect a stable
   session for shared state.
4. **Validate remote tool args against the server's JSON Schema in Tern.**
   Rejected: the server already validates. Re-validating means we'd need
   a JSON-Schema → Pydantic compiler at runtime, and any disagreement
   between the two implementations becomes our bug.

## Consequences

Good:
- D5 + D6 demoable end-to-end after S13. `tern run "fetch X, summarize"`
  works against live Bedrock in 75 minutes of build.
- Same Tool Protocol everywhere: model can't tell native from remote;
  gate, registry, span recorder all stay agnostic.
- Adding a real browser later is a drop-in swap — same tool name, same
  args model.
- MCP servers from the wider ecosystem (fetch, filesystem, github,
  postgres, …) work out of the box.

Bad:
- `web_fetch` v0 can't render JS-heavy pages. Most modern news sites
  need a real browser. Acceptable for MVP; tracked as follow-up.
- We trust the MCP server's args schema. A buggy server can crash
  mid-call; we catch the exception and report it as a tool failure but
  the model sees it as "tool errored" without rich diagnostics.
- Per-`tern run` connection cost: spawning stdio MCP servers adds
  ~200–500 ms per server on cold start. Fine for one-shot invocations,
  worth pooling for the chat REPL later.

## Follow-ups

- `tern chat` doesn't yet wire MCP (each turn is its own `asyncio.run`).
  Lift that to a single REPL-scoped event loop and reuse the manager.
- Real browser-use behind `WebFetchTool` (or a sibling `BrowseTool` if
  we want stateful navigation).
- HTTP-transport MCP servers (currently stdio-only).
- Per-tool routing into purpose-aware models (M11 territory).
