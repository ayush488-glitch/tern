---
title: "ADR-0003 — Tool surface and sandbox"
type: decision
created: 2026-05-27
updated: 2026-05-27
status: accepted
supersedes: []
superseded_by: []
tags: [tern, tools, sandbox, permissions, m5, m9, m10, phase-1]
---

# ADR-0003 — Tool surface and sandbox

## Status
Accepted, 2026-05-27.

## Context

[ADR-0001](adr-0001-jtbd-and-scope.md) commits Tern to a unified tool surface across native tools, browser-use ([entities/browser-use](../entities/browser-use.md)), and MCP servers ([entities/mcp-python-sdk](../entities/mcp-python-sdk.md)) from day 1 — even though browser and MCP land later (S13). The Tool Protocol must accommodate all three shapes from the start, or M5 forks into three competing abstractions.

Three concrete questions:

1. **What is a `Tool`?** Sync? Async? Returns what? Validates how?
2. **Permission model.** Pre-approval, post-approval, allowlist, ask-every-time? How do destructive vs read-only tools differ?
3. **How do browser-use and MCP plug in without bending the abstraction?**

Prior art:
- aider has tool-shaped concepts (commands, edit blocks) but no first-class registry; it's coder-class methods all the way down.
- claude-code has a clean Tool interface in TS with `inputSchema`, `outputSchema`, double-gated permissions ([ref-claude-code](../sources/ref-claude-code.md) §3).
- MCP defines a remote tool surface with annotations (`destructiveHint`, `idempotentHint`, etc.) — see [ref-browser-mcp](../sources/ref-browser-mcp.md) Part B.

## Decision

### One `Tool` Protocol, three implementations
```python
class Tool(Protocol):
    name: str                          # "read_file" | "browse.run" | "fetch.get"
    title: str                         # human-readable
    description: str                   # for the model's tool list
    input_schema: type[BaseModel]      # pydantic model — generates JSON schema
    output_schema: type[BaseModel] | None
    annotations: ToolAnnotations       # destructive? idempotent? read_only? open_world?

    async def invoke(
        self,
        args: BaseModel,
        ctx: ToolContext,
    ) -> ToolResult:
        ...
```

Three concrete implementations, sibling not subclass:

1. **`NativeTool`** — `read_file`, `edit_block`, `bash`, `notes_append`, etc. Lives in `src/tern/tools/`.
2. **`BrowserTool`** — single tool `browse.run(task: str, max_steps: int)`. Wraps long-lived `BrowserSession` + per-call `Agent.run()` ([entities/browser-use](../entities/browser-use.md)).
3. **`MCPTool`** — synthetic, generated at startup from `ClientSessionGroup.list_tools()`. Name-prefixed `<server>.<tool>`. `invoke` proxies `session.call_tool(name, args)`, adapts `CallToolResult → ToolResult`.

The agent core (M3) and the loop (M1) only see `Tool`. They don't know the difference. That's the point.

### Pydantic for schemas, not Zod or JSON-schema-by-hand
Pydantic v2 generates JSON Schema from Python types automatically. Strict mode catches drift. The model gets a clean tool list; the runtime gets validated args; we don't write schema twice.

```python
class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    offset: int = 1
    limit: int = 500
```

### Double-gated permissions
Two gates, both required:

1. **Filter at registry**: tool isn't visible to the model unless its `annotations` are compatible with the active mode (`safe` / `default` / `yolo`). A `--safe` invocation drops every tool with `destructive=True` from the registry before the model sees the list.
2. **Enforce at call site**: even if the tool is visible, every call passes through `PermissionGate.check(tool, args, ctx)`. Destructive calls raise `ApprovalRequested` event; the loop pauses; M2 surfaces a TUI prompt; user grants or denies.

Lifted from claude-code's pattern ([ref-claude-code](../sources/ref-claude-code.md) §4). Both gates are needed: registry-filter alone leaks if model coerces, call-site alone leaks via "I'll just describe what I would do" exfiltration.

### Modes (CLI flags, propagated through ToolContext)
- `--safe` — read-only tools only (no `edit_block`, no `bash` writes, no `browse.run` form-fills).
- `--default` — destructive tools require approval; idempotent ones don't.
- `--yolo` — all tools auto-approved (CI / scripted use only; warned at startup).

Modes are CLI flags, not config files. ADR-0001 ruled out the hosted/SaaS shape; modes are per-invocation.

### Annotations carry from MCP, applied uniformly
MCP's `ToolAnnotations` (`destructiveHint`, `idempotentHint`, `readOnlyHint`, `openWorldHint`) become Tern's canonical tool annotations. Native tools and browser tools declare them too. The PermissionGate reads annotations alone — no special-casing native vs MCP vs browser.

This is the architectural payoff of the unification: `destructive=True` triggers the same gate whether the tool is `bash` (native), `browse.click` (sub-agent action observed externally as `browse.run`), or `filesystem.write_file` (MCP).

### Sandbox boundaries
- **File writes**: scoped to repo root by default. `--allow path/...` opens specific paths outside. `~` expansion explicit. No relative-path-escape via `..`.
- **Shell**: `bash` tool runs subprocesses with the user's privileges (no Docker in v1 — too much friction for the contributor audience). Timeout per call (M12). Output streamed and truncated. Network access NOT blocked (would break too many real tasks); annotated `openWorld=True`.
- **Browser**: `BrowserSession` runs headless by default. `--headed` flag for debugging. Browser session is namespaced to Tern session id (no cookie carry-over across sessions unless explicit profile path).
- **MCP**: each server runs in its own process (stdio) or its own HTTP origin. Tern's process is the client only. No code execution from MCP into Tern's process.

These are NOT Docker / firejail / nsjail boundaries. ADR-0001 (terminal-native, runs as user) accepts that. Hardening to OS-level sandboxing is a future ADR (post-v1, when sandbox maturity warrants it).

### `ToolResult` shape
```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    content: str                      # what the model sees (text-only for now)
    artifacts: tuple[Artifact, ...]   # screenshots, file paths, structured data
    error: str | None
    metadata: dict[str, Any]          # tokens, duration, urls, exit_code, etc.
```

Lifted from browser-use's `AgentHistoryList.final_result()` shape ([ref-browser-mcp](../sources/ref-browser-mcp.md) Part A). Generalizes cleanly to native and MCP.

## Alternatives rejected

### A. `BaseTool` abstract class with shared logic
Sibling protocol implementations beat a base class because the three tool families share NOTHING except the public contract. Native tools are pure functions; browser tools wrap a long-lived session + sub-agent; MCP tools are RPC proxies. A base class would either be empty (no win) or grow a god-class cluster of conditionals. Rejected for the same reason ADR-0004 rejects `BaseProviderAdapter`.

### B. Per-tool-family permission gate
Three gates (one for native, one for browser, one for MCP) lets each family carry its own annotation vocabulary — at the cost of triplicating the most security-critical code in the system. One gate, one annotation schema, one place to audit.

### C. Always-approve / always-deny flags per tool
Too coarse. Real users want "read_file always, edit_block always for these paths, bash always for these commands." That's a future feature (`tern.toml` allowlist). v1 keeps modes simple (`safe`/`default`/`yolo`) and lands granular allowlists post-v1.

### D. Docker / firejail sandbox in v1
Adds install friction (Docker daemon, image pulls), breaks on Windows, adds latency per shell call. The contributor audience runs on macOS / Linux laptops; they're already running the agent against their own checkout. The trust model in ADR-0001 is "user-machine, user-keys, user-bill"; OS-level sandboxing is a strict upgrade we'll take later when the threat model warrants the friction.

### E. Streamed `ToolResult` (token-by-token output)
Useful for TUI polish, not v1. `ToolResult` is one-shot. Streaming lands in M2 polish (S15) and is opt-in per tool via `supports_streaming: bool`.

## Consequences

### Positive
- M5 has ONE concept the rest of the system imports. Adding a new tool family (e.g. SSH-execed remote tools) is a third sibling, not a refactor.
- D5 (browser) and D6 (MCP) plug in at S13 without touching M3 / M1 / M4.
- Pydantic + JSON Schema means tool docs, validation, and provider-side schema all derive from one source.
- Permission gate is the single audit point for destructive actions. M13 (security) decorates around it.

### Negative / accepted costs
- Pydantic v2 dependency lands at v1. Acceptable; everyone in the ecosystem uses it.
- `--yolo` mode is a footgun. Mitigated by startup-time warning and audit log.
- No OS-level sandbox means `bash` tool runs with user privileges. Mitigated by approval gate and audit log; documented in README under "Trust model."

### Open questions deferred
- Allowlist file (`.tern/allowlist.toml`) for path/command-level pre-approval — post-v1.
- Concurrent tool calls — schema supports it, scheduler doesn't (single-flight in v1).
- Tool-output redaction by default (M13 entropy redaction over `ToolResult.content`) — implementation in S14.

## References
- [ADR-0001 jtbd-and-scope](adr-0001-jtbd-and-scope.md) — anchor.
- [ADR-0002 runtime-shape](adr-0002-runtime-shape.md) — sub-agent contract sits at this boundary.
- [ADR-0004 provider-layer](adr-0004-provider-layer.md) — Tool Protocol's `input_schema` ↔ provider's tool list.
- [ADR-0005 session-state](adr-0005-session-state.md) — every `ToolResult` becomes a turn-object content block.
- [entities/browser-use](../entities/browser-use.md) — D5 implementation surface.
- [entities/mcp-python-sdk](../entities/mcp-python-sdk.md) — D6 implementation surface.
- [ref-claude-code](../sources/ref-claude-code.md) — double-gated permissions lifted.
- [ref-browser-mcp](../sources/ref-browser-mcp.md) — annotation vocabulary, sub-agent contract.
