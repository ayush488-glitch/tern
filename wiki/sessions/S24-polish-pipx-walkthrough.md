---
title: S24 — M14 Polish, pipx v0.1.0, Walkthrough Notes
type: session
created: 2026-05-29
updated: 2026-05-29
tags: [tern, s24, polish, pipx, walkthrough, slash-commands]
---

# S24 — M14 Polish + pipx v0.1.0 + Walkthrough Notes

## What was built

### M14 polish (ui/app.py)

Wired all S22–S23 tools into the chat REPL registry:
  WebSearchTool, ScreenshotTool, ProcTool,
  BrowserNavigateTool, BrowserSnapshotTool,
  BrowserClickTool, BrowserTypeTool, BrowserVisionTool

Added `/model [id]` — show current model or switch for next turns.
`_override_model: str | None` declared before the loop; per-turn adapter selection
branches on it. `/model` without arg shows "auto (cost router)" or the override.

Added `/clear` — clear history + reset turn_idx + parent_sha.

Added `/mode [mode]` — show or set permission mode live. Rebuilds PermissionGate
on change so destructive-tool prompt behaviour updates immediately.

Added `/tools` — lists all tools visible in current mode with destructive/net flags.
`_cmd_tools(registry, console, mode)` helper calls `registry.visible_to_model(mode=mode)`.

Added `/cost` — prints `rec.total_cost_usd()` so far.

Expanded `_HELP` to list all slash commands with descriptions.

### --print mode (cli.py)

`tern run "..." --print` streams raw LLMTextDelta.text to stdout (no Rich),
suppresses all span/cost UI, adds trailing newline. Suitable for piping:
  tern run "summarise this file" --print > summary.txt

LLMTextDelta added to cli.py imports. print_mode param added to run().

### v0.1.0 bump

src/tern/__init__.py: __version__ = "0.1.0"
pyproject.toml: version = "0.1.0", Development Status → Alpha
httpx added to core dependencies (web_search needs it)
browser optional extra: `pip install tern[browser]` pulls playwright
all extra: `pip install tern[all]`

tern --version prints "tern 0.1.0". Confirmed.

### Walkthrough notes (5 chapters)

.scratch/walkthrough-notes/ (gitignored):
  ch01-why-tern.md         — JTBD, six differentiators, S1–S5 summary
  ch02-turn-loop.md        — ADR-0002, async generator, event types, double-gate
  ch03-canonical-messages.md — provider layer, cost routing, ImageBlock
  ch04-memory-skills.md    — three context layers, caps, repo memory, skills
  ch05-browser-vision.md   — five browser tools, web_search, vision pipeline

Each chapter ends with a teaching hook — the trap students fall into + Tern's answer.

## Tests

498/498 passed, +8 new (test_s24_polish.py).
ruff 0 errors. mypy --strict 74 source files 0 errors.

## What's next

Tern is now feature-complete for v0.1.0:
  - 24 sessions, all six differentiators shipped
  - 74 source files, 498 tests
  - `tern --version` prints 0.1.0
  - browser, vision, search, memory, skills, replay, MCP all live

Next: README polish, real PyPI publish, or start a new capability arc.
