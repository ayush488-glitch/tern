---
title: S21 — Long-Running Build Hardening
type: session
created: 2026-05-29
updated: 2026-05-29
sources: [decisions/adr-0012-long-running-build-hardening.md]
tags: [tern, s21, hardening, loop, proc, budget, cache, diff, summarize, delegate]
---

# S21 — Long-Running Build Hardening

## What was built

All six ADR-0012 primitives shipped in one session.

### Primitive 1: Working-set summarizer (`src/tern/loop/summarize.py`)
When a single turn accumulates 30+ tool-result blocks (default threshold), older results
get compressed into a single synthetic summary message. Recent 10 blocks stay verbatim.
No LLM call needed — pure Python. Wired into `run_turn()` in `loop.py` at step start.
ADR-0002 compliant: intra-turn only, canonical log never modified.

### Primitive 2: Sub-turn delegation (`src/tern/loop/delegate.py`)
`DelegateTool` spawns a child `Turn` with isolated context. Parent sees only the child's
final text reply. Child runs `run_turn()` internally, times out cleanly. Registered in
`cli.py` tool registry. Recursive delegation blocked (child gets `registry=None`).

### Primitive 3: Background proc tool (`src/tern/tools/native/proc.py`)
`ProcTool` mirrors Hermes `process()`. Actions: start, poll, wait, kill, log, list.
Async stdout drain with 200 KiB cap. Inherits bash deny-list patterns. Registered in cli.py.

### Primitive 4: Read-result cache (`src/tern/loop/read_cache.py`)
Content-addressed cache keyed by (path, mtime_ns, size). Full-file reads only.
`get_session_cache()` singleton, cleared on each turn start (`reset_session_cache()`).
`read_file.py` patched: hit returns `cached: True + sha256` in metadata, miss stores entry.

### Primitive 5: Diff preview (`src/tern/loop/diff_preview.py` + events)
`unified_diff()` and `line_count()` helpers. `write_file.py` computes diff on overwrite
and embeds it in `ToolResult.metadata["pending_diff"]`. `DiffPreviewEvent` added to
`TurnEvent` union for downstream rendering.

### Primitive 6: Cost budgets (`src/tern/loop/budget.py`)
`BudgetTracker` with `session_limit` and `turn_limit` (USD). `BudgetStatus` enum:
OK / SOFT_WARN / HARD_EXCEEDED. Loads from `~/.tern/config.json` keys `budget.session`
and `budget.turn`. Config key allowlist updated in `config.py`.

## Numbers
- ruff: 0 errors
- mypy --strict: 0 errors in 71 source files
- pytest: 451 passed, 1 skipped (+29 new S21 tests)

## What's next
S22 — vision: `ImageBlock` wired through Bedrock-Anthropic adapter + `screenshot` tool.
