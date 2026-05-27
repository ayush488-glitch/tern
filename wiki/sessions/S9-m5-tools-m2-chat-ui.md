---
title: S9 — M5 tools + M2 chat UI (first agentic demo)
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [session, s9, m5, m2, tools, permissions, textual, agent-loop]
---

# S9 — M5 tools + M2 chat UI

End of S9: tern is now an agent. The model can call `read_file` and
`edit_block`, the loop dispatches them through the registry, the permission
gate blocks destructive calls until the human says y, and the whole thing
runs inside a Textual TUI. `TERN_LIVE=1 tern chat` is the new demo surface;
`tern run` still works as the one-shot smoke test.

## What was built

Four commits, each independently green:

1. **m5: tool protocol + registry + permission gate** (S9 commit 1)
   - `src/tern/tools/protocol.py` — `Tool` Protocol, `ToolAnnotations`,
     `ToolResult`, `ToolContext` with `resolve_under_repo()` sandbox helper
   - `src/tern/tools/registry.py` — gate 1, mode-based filter (default / safe / yolo)
   - `src/tern/tools/permissions.py` — gate 2, `PermissionGate.check()`,
     `ApprovalDecision`, prompter callback, `ToolBlocked` exception
   - 13 unit tests
2. **m5: read_file + edit_block native tools** (S9 commit 2)
   - `src/tern/tools/native/read_file.py` — line-numbered chunks, 1-indexed
     offset, `limit ≤ 2000`
   - `src/tern/tools/native/edit_block.py` — exact match → whitespace-tolerant
     match (lifted from aider's `perfect_or_whitespace`); `EditBlockError` on
     ambiguity or no-match. `apply_edit_block()` exposed as a pure helper.
   - 15 unit tests
3. **m1+m5: agentic multi-step loop, tool execution, reflection retry** (S9 commit 3)
   - `core/turn.py` — `Turn` gains `registry`, `gate`, `mode`, `repo_root`, `max_steps`
   - `core/loop.py` — multi-step loop. Per step: emit `LLMRequested`, await
     adapter, emit `LLMResponded`, append assistant message; for each
     `ToolCallBlock` validate args (Pydantic), gate-check (with
     `ApprovalRequested/Granted/Denied` if destructive), invoke, emit
     `ToolCalled` + `ToolReturned`. ValidationError or unknown tool ⇒
     `ReflectionTriggered` and a `tool_result(ok=False)` block fed back so the
     model can self-correct. Closes on `end_turn`, `max_steps`, or
     `permission_denied`.
   - 10 new loop tests (scripted adapter, denial path, max_steps cap,
     reflection retry, safe-mode filter, approval pair, S8 back-compat)
4. **m2: textual chat ui with permission modal + slash commands** (S9 commit 4)
   - `src/tern/ui/app.py` — `ChatApp(App)`: header, `RichLog`, input dock,
     footer; rolls assistant + tool messages forward across turns; `/exit`
     slash command; per-event one-liners (llm cost, tool calls, approvals,
     turn done). `PermissionModal(ModalScreen[bool])` y/n overlay with
     escape-deny.
   - `tern chat` typer command, `--mode {default,safe,yolo}` flag, `TERN_LIVE`
     gate.

## Demoable end-to-end

```
TERN_LIVE=1 tern chat
> read src/tern/core/loop.py and tell me what run_turn does
· llm us.anthropic.claude-sonnet-4-20250514-v1:0 in=… out=… $…
· tool read_file({"path": "src/tern/core/loop.py"})
· ← read_file ok (3,054B)
· llm … (final reply)
tern run_turn is the agent's main async generator. It builds a per-step
LLMRequested → LLMResponded pair, then for each ToolCallBlock it validates,
gates, invokes, and emits ToolCalled/ToolReturned. …
· turn done: done
```

Edits go through the modal:

```
> rename `run_turn` to `execute_turn` everywhere in src/tern/core/loop.py
· tool edit_block({"path": "src/tern/core/loop.py", ...})
[modal] edit_block wants to run.   [y] approve   [n] deny
```

## Gates entering S10

- pytest **92/92** ✅ (was 54 entering S9)
- ruff ✅
- mypy --strict ✅ on 27 src files (textual stubs ignored via override)
- `tern --version` ✅
- `tern run` live Bedrock call ✅ (smoke test still works after loop rewrite)
- New: `tern chat` registered, modal compiles, no live test (interactive only)

## Pitfalls caught + logged

1. **Pydantic invariance on `args_model`** — Test fakes need
   `args_model: type[BaseModel]` annotated explicitly; subclasses don't
   substitute under invariance. Same for the `Tool` Protocol — kept the
   annotation broad in the abstract surface, narrowed in concrete tools.
2. **edit_block ambiguity error message ordering** — When the search string
   appears literally `N>1` times via exact match, raise "appears N times"
   immediately. Whitespace-tolerant fallback only fires when exact match misses.
   Test was reshaped to construct a case where whitespace path is the one that
   finds duplicates.
3. **Textual classes can't subclass under mypy --strict** because the stubs
   are missing — `# type: ignore[misc]` on `class ChatApp(App[None])` and
   `class PermissionModal(ModalScreen[bool])`, plus a `tool.mypy.overrides`
   block for `textual.*` in pyproject.
4. **`BINDINGS` mutable class attribute** — Ruff RUF012 wants `ClassVar[list[Binding]]`.
5. **mypy strict on tests is noisy** — sticking with the S8 baseline of
   src-only strict. Tests are smoke-checked at runtime via pytest only.

## What's next (S10)

Roadmap milestone: **M3 sessions + persistence + replay**. Tern currently
loses the conversation when the chat app exits. S10 wires:

- `~/.tern/sessions/<id>/` directory layout (canonical message log NDJSON +
  spans NDJSON already shipped)
- `tern resume <prefix>` — load a previous session, replay events into the
  recorder, hand control back to chat with the rolling messages preserved
- `tern sessions` — list recent sessions with cost / message count / last touched
- D3 (per-turn replay/branch) starts here: every turn writes an immutable
  snapshot, branching is a fork operation on those snapshots.

After S10 lands, the demo is "open tern, do work, close it, come back tomorrow,
keep going" — first time the project is genuinely useful as a tool, not a tech
demo.
