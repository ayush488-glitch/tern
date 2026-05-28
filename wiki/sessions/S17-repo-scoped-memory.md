---
title: S17 — Repo-scoped memory tier (Layer A)
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [s17, memory, repo-memory, adr-0011, layer-a]
---

# S17 — Repo-scoped memory tier (Layer A)

## What shipped

### New module: `src/tern/memory/repo_store.py`

Layer A of the operational memory moat (ADR-0011 §S17).

Storage layout:
    <repo_root>/.tern/memory/ARCH.md       — architecture decisions
    <repo_root>/.tern/memory/DECISIONS.md  — short-form ADRs
    <repo_root>/.tern/memory/FAILURES.md   — failure patterns + fixes
    <repo_root>/.tern/memory/REVIEWERS.md  — reviewer preferences

Key functions:
- `find_repo_root(cwd)` — walks up from cwd looking for `.git` or `.tern`. Returns None when no marker found.
- `load_repo_memory(target, repo_root)` — returns (entries, raw_text). Empty tuple + '' on absent file.
- `add_repo_entry / replace_repo_entry / remove_repo_entry` — same atomic write pattern as global store.
- `render_repo_banner(repo_root)` — renders the REPO MEMORY banner. Empty string when all files empty.

### Extended: `src/tern/memory/store.py`

Added `render_all_banners_with_repo(cwd)` — composes all three tiers in canonical order:

    ══ MEMORY (your personal notes) ══      ← global MEMORY.md
    ══ REPO MEMORY (./.tern/memory) ══     ← per-repo ARCH/DECISIONS/FAILURES/REVIEWERS
    ══ USER PROFILE (who the user is) ══   ← global USER.md

Per ADR-0002: repo memory is injected into the system prompt of the new turn. It never mutates the canonical message log.

### Extended: `src/tern/tools/native/memory_tool.py`

Added `scope: "global" | "repo"` field to `MemoryArgs` (default: "global"). Backward compatible — all existing calls without `scope` continue to work unchanged.

- `scope="global"` — routes to `~/.tern/memory/MEMORY.md` or `USER.md` (targets: `memory | user`)
- `scope="repo"` — routes to `<repo_root>/.tern/memory/{ARCH,DECISIONS,FAILURES,REVIEWERS}.md` (targets: `arch | decisions | failures | reviewers`)

Repo root resolution: prefers `ctx.repo_root` (already wired from CLI), walks up if needed, returns error when no root found.

### Extended: `src/tern/skills/catalog.py`

`build_system_prompt(...)` now accepts `cwd: Path | None` and forwards it to `render_all_banners_with_repo`. `include_memory=False` still works for test isolation.

### Updated: `src/tern/cli.py`

Both `tern run` and `tern chat --resume` now pass `cwd=cwd or Path.cwd()` to `build_system_prompt`.

## Gates

- pytest **327/327** (was 296; +31 repo memory tests in `test_repo_memory.py`)
- ruff ✅
- mypy --strict ✅ (53 source files)
- live smoke: `test_s17_smoke.py` (skips without `TERN_LIVE=1`; all assertions verified via pytest)

## Tests added (`tests/test_repo_memory.py`, 31 tests)

- `find_repo_root` via `.git`, via `.tern`, walks upward, no-marker fallback, `.tern` wins over ancestor `.git`
- load/add/replace/remove round-trips for each target; error cases (empty content, ambiguous match, no match)
- atomic write: no temp files left behind
- `render_repo_banner`: empty → '', populated with correct sections and order (ARCH < DECISIONS < FAILURES < REVIEWERS)
- banner composition order: MEMORY < REPO MEMORY < USER PROFILE
- absent-repo fallback: `render_all_banners_with_repo` graceful when no repo
- `MemoryTool` scope routing: global default, repo add/replace/remove, no-root error, unknown scope, unknown repo target
- `build_system_prompt` threads cwd to repo memory in banner

## Design decisions worth keeping

- **No new deps** — repo_store mirrors global store's stdlib-only atomic write pattern.
- **Scope default "global"** — zero breaking change. Old calls to `memory` tool work identically.
- **Repo detection at tool call time** — not at startup. This means `tern run` inside /tmp produces no repo banner, which is correct.
- **Banner order locked** — MEMORY (global notes), REPO MEMORY, USER PROFILE. Consistent with the "who am I" ordering (self-notes first, repo context second, user identity last).
- **Empty files = no banner** — same policy as global store. Fresh repo doesn't burn tokens.

## Deferred

- Layer B observers (git/PR outcome spans for Bayesian priors) — S19.
- Router + KNN recall — S18.
- `tern recall <prompt>` CLI surface — S18.

## Next session

S18 — per-turn cognitive router (decision tree → Nova Micro fallback) + per-repo KNN recall (Bedrock Titan Embeddings). ADR-0011 subsystems 1+2. Both land in `src/tern/router/` and `src/tern/recall/`.
