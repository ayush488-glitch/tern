---
title: S18 — Cognitive Router + KNN Recall
type: session
created: 2026-05-29
updated: 2026-05-29
sources: [decisions/adr-0011-cognitive-routing-and-recall.md]
tags: [tern, router, recall, knn, bedrock, titan, nova-micro, s18]
---

# S18 — Cognitive Router + KNN Recall

## What was built

### D1 — Cognitive Router (`src/tern/router/`)
Two modules + package init:

- `classify.py` — regex-first heuristic classifier. 4 rule groups (ARCH, LINT,
  BOILERPLATE, CODE), ordered by priority. Zero-cost regex pass fires first.
  Nova Micro LLM fallback fires only on a miss (one short call, ~$0.0001).
  Returns `(TurnPurpose, Method)` where Method is "regex" | "llm" | "default".

- `route.py` — thin wrapper: calls `classify`, looks up `model_for_purpose` from
  the existing routing table, returns `(TurnPurpose, model_id, Method)`.

- `__init__.py` — exports `classify`, `route`.

`--purpose` default changed from `"code"` to `"auto"` in `tern run`.
Explicit `--purpose arch|code|lint|boilerplate` still works (bypasses router).
`--model` override still wins over everything.

### D2 — KNN Recall (`src/tern/recall/`)
Three modules + package init:

- `embed.py` — Bedrock Titan Text Embeddings v2 (1024-dim). Single public fn
  `embed(text) -> list[float]`. Falls back to zero-vector on any error — embed
  failure must never kill a turn.

- `store.py` — `RecallStore`: per-repo KNN index at `<repo>/.tern/recall/`.
  `vectors.npy` (float32, shape N×1024) + `metadata.jsonl` (one JSON line per
  row). Atomic writes on both. `add()` appends; `query()` returns top-k by
  cosine similarity (brute-force, fine for N < 50k).

- `banner.py` — `render_recall_banner(hits) -> str`. Empty string when no hits.

- `__init__.py` — exports `RecallStore`, `RecallHit`, `render_recall_banner`.

### Banner order (4 tiers)
`render_all_banners_with_repo` in `store.py` now accepts `recall_hits`:
1. global MEMORY (`~/.tern/memory/MEMORY.md`)
2. REPO MEMORY (`.tern/memory/ARCH|DECISIONS|FAILURES|REVIEWERS`)
3. SIMILAR PAST TURNS (KNN recall — empty if no hits)
4. USER PROFILE (`~/.tern/memory/USER.md`)

`build_system_prompt` in `catalog.py` accepts `recall_hits` and forwards it.

### Observability (events)
Two new events in `events.py` + `TurnEvent` union:
- `RoutingClassified` — fired after router; captures prompt_preview, purpose,
  method ("regex"|"llm"|"default"), model_id.
- `RecallQueried` — fired after recall; captures n_candidates, n_hits.

Both are emitted in `tern run` immediately after `asyncio.run(_go())`.
Both use `parent_id=turn.id` so they nest correctly in the span tree.

### CLI additions
- `tern recall [QUERY]` — query the local index; no QUERY shows index stats.
- `tern recall add <PROMPT> <REPLY>` — seed the index manually.

## Numbers
- ruff: clean
- mypy --strict: 60 files, 0 errors
- pytest: 368 passed, 1 skipped (live smoke)
  - 22 new tests in test_s18_router.py
  - 19 new tests in test_s18_recall.py
- numpy added to pyproject.toml deps (was transitive, now explicit)

## Key decisions
1. Regex-first, LLM fallback — not LLM-first. Zero cost on most turns; Nova
   Micro only on ambiguous prompts. Consistent with cost-consciousness.
2. KNN is brute-force cosine on numpy — no vector DB dependency. Titan v2
   gives 1024-dim normalised embeddings; cosine = dot product on normalised.
3. Recall failure is silent — `try/except Exception: pass` around every
   Bedrock call in the turn path. Recall is additive, never load-bearing.
4. `--purpose auto` is new default in `tern run`. Old `--purpose code` still
   works. Backward-compatible: tests that don't pass a purpose get "auto" now,
   which resolves to CODE for non-matching prompts — same effective behaviour.
5. Recall index lives at `<repo_root>/.tern/recall/` — separate from
   `.tern/memory/` (repo memory). Kept separate because recall is ephemeral
   (grows unbounded, may be pruned) vs. memory files are curated.
6. `tern run` emits RoutingClassified + RecallQueried after `asyncio.run(_go())`
   not before — those events are metadata, not part of the turn stream.

## ADR compliance
- ADR-0002: recall hits inject into system prompt via `build_system_prompt`;
  never mutate the canonical message log.
- ADR-0011 §1 (cognitive router): done. §2 (KNN recall): done.
  §3 (embeddings as first-class retrieval): foundation laid (Titan v2).

## What's next
S19 (per AGENTS.md / ADR-0011): curator subsystem — surfaces stale/orphaned
repo memory entries, suggests edits, auto-prunes. Builds on S17 repo store
and S18 recall index.
