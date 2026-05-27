---
title: mcp-python-sdk
type: entity
created: 2026-05-27
updated: 2026-05-27
sources: [../sources/ref-browser-mcp.md]
tags: [reference, mcp, d6, m10]
---

# mcp-python-sdk

The official Python SDK for Model Context Protocol. Tern's D6 MCP client.

Repo (cloned, gitignored): `.scratch/grounding/refs/python-sdk`.

## Client surface we use
`mcp.ClientSession, mcp.StdioServerParameters, mcp.client.stdio.stdio_client, mcp.client.streamable_http.streamablehttp_client, mcp.client.session_group.ClientSessionGroup, mcp.client.auth.OAuthClientProvider`.

## Primitives we surface
- **tools (PRIMARY)** — name, title, description, inputSchema, outputSchema, annotations (`readOnlyHint, destructiveHint, idempotentHint, openWorldHint`).
- **prompts** — parameterized message templates → Tern slash commands.
- **resources** — addressable read-only context → expose as virtual `<server>.read_resource` tool.
- **roots / sampling / elicitation** — DEFER to v1.1.

## Transports
- **stdio** — default. Local subprocess. 90% of community servers.
- **streamable_http** — current spec's HTTP transport. Use for remote/hosted MCP services.
- **sse** — legacy compat.

## Integration plan
Tern defines one internal `Tool` interface. On startup, registry loads native tools + one `MCPClientManager` wrapping `ClientSessionGroup`. For each configured server, calls `initialize + list_tools + list_prompts + list_resources` and registers each remote tool as a synthetic native Tool whose `invoke` proxies to `session.call_tool(name, args)` and adapts `CallToolResult → ToolResult`.

Namespacing: `<server>.<tool>` to avoid collisions. Annotations pass through so `destructiveHint==true` triggers Tern's permission gate identically to native tools.

See [sources/ref-browser-mcp.md](../sources/ref-browser-mcp.md) Part B for the full integration spec.
