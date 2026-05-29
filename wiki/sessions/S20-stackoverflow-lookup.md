---
title: S20 — StackOverflow Error Lookup
type: session
created: 2026-05-29
updated: 2026-05-29
sources: [decisions/adr-0011-cognitive-routing-and-recall.md]
tags: [tern, s20, lookup, stackoverflow, error-recovery]
---

# S20 — StackOverflow Error Lookup

## What was built

**`src/tern/lookup/` — new package (4 files)**

- `search.py` — SO API v2.3 client. No auth required (300 req/day free; 10k with `STACK_APPS_KEY`). `search(query, n=3)` returns `list[SOHit]`, regex-first classification on title + tags. `extract_error_query(tool_outputs)` pulls the most relevant error line. `_get()` gzip-decompresses responses. `_fetch_bodies()` batch-fetches accepted/top answer bodies and strips HTML via `HTMLParser`.
- `inject.py` — `build_so_banner(hits)` renders the "SIMILAR ERRORS (Stack Overflow)" banner (same visual shape as REPO MEMORY / SIMILAR PAST TURNS). Truncates answer preview at 600 chars.
- `store.py` — `save_so_hits()` + `load_and_clear_so_hits()`. Atomic writes. Persists hits to `~/.tern/memory/so_hits.json`. File is deleted on first read (one-turn lifetime). Respects `TERN_HOME` env override.
- `__init__.py` — re-exports `SOHit`, `search`, `fetch_answer_body`.

**`src/tern/core/events.py`** — added `SOLookupCompleted` event. Added to `TurnEvent` union.

**`src/tern/cli.py`** — two wiring points:
1. After `log_outcome`: if `_s19_error_count >= 1`, calls `extract_error_query` then `search`, saves hits via `save_so_hits`, emits `SOLookupCompleted` span, prints cyan status line.
2. At start of each `run` call: `load_and_clear_so_hits()`, `build_so_banner()`, appended to `sys_text` if non-empty. This is the "next turn injection" — hits from turn N surface in turn N+1's system prompt.

**ADR-0002 compliance**: SO hits live in system prompt only (file → banner → sys_text). Never touch the canonical message log.

## Numbers

- ruff: 0 errors (64 source files)
- mypy --strict: 0 errors (64 source files)
- pytest: 422 passed, 1 skipped (+26 tests from `tests/test_s20_so_lookup.py`)

## What's next

S21 (ADR-0012): long-running build hardening — streaming tool output, partial results on timeout, checkpoint resume. See `wiki/decisions/adr-0012-long-running-build-hardening.md`.
