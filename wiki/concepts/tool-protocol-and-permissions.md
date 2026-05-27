---
title: Tool protocol and the double permission gate
type: concept
created: 2026-05-27
updated: 2026-05-27
sources:
  - sources/aider-readme.md
  - sources/claude-code.md
tags: [tool-protocol, permissions, m5, adr-0003]
---

# Tool protocol and the double permission gate

The product question: how does Tern let a model do dangerous things on the
user's machine without (a) being annoying, (b) being unsafe, (c) being
unfair to one provider's tool-call shape over another's?

The answer is two gates in series, with a single Tool Protocol that everything
plugs into. Per [ADR-0003](../decisions/adr-0003-tool-protocol.md).

## The protocol

`tern.tools.protocol.Tool` is a runtime-checkable Protocol with four members:

```python
class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]
    annotations: ToolAnnotations
    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

Two design choices to call out:

- `args_model` is a Pydantic v2 BaseModel with `model_config = {"extra": "forbid"}`.
  The model schema is what we ship to the provider; the validated instance is
  what the tool sees. There's no string parsing, no manual schema dance.
- `ToolContext` carries `repo_root`, `session_id`, `mode`. `ctx.resolve_under_repo(p)`
  is the sandbox helper — every native tool calls it before reading or writing.
  Path traversal goes through this single gate.

`ToolAnnotations` carries the safety story:

```python
@dataclass(frozen=True)
class ToolAnnotations:
    destructive: bool          # mutates state, talks to network, etc.
    read_only: bool            # pure read; safe in any mode
    requires_approval: bool    # true ⇒ gate 2 always asks
    affected_modes: tuple[str, ...] = ("default",)  # which modes show this tool
```

## Gate 1 — registry filter

`Registry(tools).specs(mode=…)` returns the `ToolSpec` tuple that the loop
hands to the adapter. In `safe` mode, anything `destructive=True` is dropped
**before** the model sees it. The model literally cannot call what isn't in
its tool list. This is the cheap, fast layer.

`safe` is the default for any non-trusted environment (CI, demos, public
sessions). `default` is the user's normal workstation. `yolo` is "let the
model rip" — auto-approves destructive calls without prompting.

## Gate 2 — call-site permission

`PermissionGate.check(tool, args, ctx)` runs after the model has already
chosen to call a tool but before `tool.invoke()` fires. It looks at:

- `ctx.mode` — `safe` raises `ToolBlocked("refused in safe mode")`; `yolo`
  short-circuits to `GRANTED`
- `tool.annotations.destructive` — for `default` mode, destructive tools
  trigger the prompter; non-destructive auto-approve
- the prompter is a callable injected by the host (CLI, TUI, test fake).
  It returns `ApprovalDecision.GRANTED | DENIED`.

If the gate denies, the loop:

1. emits `ApprovalDenied` (paired with the earlier `ApprovalRequested`)
2. writes a `tool_result(ok=False, error="user denied")` block back into
   the canonical log
3. closes the turn with `reason="permission_denied"`

The user denying is a hard stop, not a "try again with different args"
signal. Validation errors (bad args) and unknown tools, by contrast, ARE
"try again" — they trigger `ReflectionTriggered` and feed the error back
in the next step.

## Why two gates and not one

A single gate at call site would technically work, but you'd be paying for
a round trip every time the model tries to call something it never should
have seen. Filtering at spec-list time (gate 1) is free — the model just
doesn't know that tool exists. Gate 2 only fires for the tools the model
legitimately had reason to call.

The two gates also separate concerns:

- **Gate 1** is a static policy decision (mode → tool visibility). No async,
  no I/O, just a filter.
- **Gate 2** is a runtime decision (does this specific call deserve a prompt?).
  Async, can prompt the user, can fail.

This is the same shape Claude Code, Aider, and Cursor end up at, just
spelled differently. We're not inventing it; we're lifting it cleanly.

## What native tools look like

`read_file` is non-destructive, read-only — gate 1 keeps it in every mode,
gate 2 auto-approves. `edit_block` is destructive — gate 1 hides it in `safe`,
gate 2 prompts in `default`, auto-approves in `yolo`.

Both tools resolve their `path` argument through `ctx.resolve_under_repo()`,
so even with `yolo` the model can't escape the project root via `../../../etc/passwd`.
That's a third gate, but it lives inside the tool implementation, not in the
permission system.

## See also

- [adr-0003-tool-protocol.md](../decisions/adr-0003-tool-protocol.md)
- [agent-turn-loop.md](agent-turn-loop.md)
- [canonical-message-log.md](canonical-message-log.md)
