---
title: S19 — Curator Subsystem (Outcome Spans + Proposal Distiller + tern curate)
type: session
created: 2026-05-29
updated: 2026-05-29
sources: [decisions/adr-0011-cognitive-routing-and-recall.md]
tags: [tern, curator, outcomes, proposals, bayesian-priors, s19]
---

# S19 — Curator Subsystem

## What was built

S19 completes ADR-0011's three-subsystem intelligence layer. The curator is the
feedback loop that turns past turn outcomes into structured repo memory edits.

### 1. OutcomeSpan event (events.py)

New frozen dataclass in `TurnEvent` union. Fired once per turn after the LLM
responds. Carries ground-truth signals:

- `tests_passed: bool | None` — detected from tool output patterns
- `commit_landed: bool | None` — detected from git commit output patterns
- `user_correction: bool` — False at emit time; retroactively settable
- `purpose`, `model_id`, `tool_names`, `error_count`, `prompt_preview`

ADR-0002 holds: the span is emitted into the span recorder and logged to
`outcomes_log.jsonl`. It never mutates the canonical message log.

### 2. curate.py extended (v0 → v1)

v0 was append-on-success hints only. v1 adds:

**OutcomeLogger:**
- `detect_tests_passed(tool_outputs)` — regex over "N passed / N failed" patterns
- `detect_commit_landed(tool_outputs)` — regex over `[branch hash]` git commit lines
- `is_correction(text)` — regex for user-correction triggers
- `OutcomeRecord` dataclass + `log_outcome()` — appends to `~/.tern/memory/outcomes_log.jsonl`
- `read_outcomes(limit=100)` — deserializes most recent records

**ProposalDistiller:**
- `CurationProposal` dataclass — typed diff proposal (target, action, content, reason, source)
- `distill_proposals(repo_root)` — reads queue + outcomes, generates proposals:
  - queue pitfall nudges → FAILURES.md proposals
  - queue procedure nudges → DECISIONS.md proposals
  - outcome test-fail turns → FAILURES.md (up to 3 most recent)
  - outcome pass pattern (≥3/5 same purpose passing) → DECISIONS.md
  - outcome user-correction turns → FAILURES.md (up to 2 most recent)
- `read_proposals(repo_root)` / `clear_proposals(repo_root)`
- `apply_proposal(repo_root, proposal)` — atomically applies via `add/replace_repo_entry`

### 3. OutcomeSpan wiring in cli.py

`tern run` now accumulates `_s19_tool_names`, `_s19_tool_outputs`, `_s19_error_count`
inside `_go()` by inspecting `ToolCalled` / `ToolReturned` events as they stream.
After `asyncio.run(_go())`:
- Builds and emits `OutcomeSpan` into the span recorder
- Calls `log_outcome(OutcomeRecord(...))` to persist to disk (best-effort, never kills a turn)

### 4. tern curate CLI

Two subcommands added:

**`tern curate` (interactive review):**
- Clears stale proposals, calls `distill_proposals()`
- Presents each proposal: target / action / content / reason
- User accepts (y), skips (n), or quits (q)
- `--yes` flag for non-interactive auto-accept
- `--dry-run` flag to preview without applying
- Applied proposals go to `.tern/memory/{arch,decisions,failures,reviewers}.md`

**`tern curate status` (read-only):**
- Shows queue nudge count, outcome span count
- Distills and lists proposals without applying

## Numbers

- ruff: clean (0 errors)
- mypy --strict: 60 source files, 0 errors
- pytest: **396 passed, 1 skipped** (28 new S19 tests added)
- New files: `tests/test_s19_curator.py`
- Modified: `src/tern/core/events.py`, `src/tern/memory/curate.py`, `src/tern/cli.py`

## Next session

S20: StackOverflow lookup on error spans. When `OutcomeSpan.error_count >= 1`,
surface the error text, search SO, inject relevant snippets into the next turn's
system prompt. Now justified — we have failure data to search against.
"""
