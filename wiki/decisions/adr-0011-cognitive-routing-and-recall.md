---
title: ADR-0011 — Per-turn cognitive routing, similarity recall, and operational priors
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [routing, knn, bayes, memory, ml, d1, moat]
sources: []
---

# ADR-0011 — Per-turn cognitive routing, similarity recall, and operational priors

## Context

S15 shipped global memory. S16 shipped multi-model adapters with a static
`_MODEL_FOR_PURPOSE` map and a per-invocation `--model` flag. That is not D1.
Real D1 is **per-turn cost routing** — the agent classifies what kind of work
the turn is, routes to the right model at the right cost, and passes only the
context that turn needs.

Separately, the user's "operational memory as moat" thesis (recorded in
session notes pre-S17) argued that durable agent value comes from compounding
repo-scoped memory plus an observation loop, not from "wrapping a bigger
model". A long discussion mapped nine traditional ML algorithms onto agent
design. The honest read is that most of them are already inside an LLM and
re-implementing them buys nothing. **Three earn real space in Tern**:

- **KNN** — similarity recall over per-repo spans. The agent remembers what
  already worked *in this repo*. Sonnet cannot do this; only our store can.
- **Decision tree (cheap → LLM-fallback)** — per-turn purpose classifier
  feeding the model router. Heuristic regex first, Nova Micro fallback,
  every routing decision logged as a span.
- **Bayesian priors via the curation queue** — S15's queue + per-turn
  outcome spans (commit accepted? tests pass? user corrected?) become priors.
  After ~100 repo-turns there is a real signal: "when the prompt looks like
  X in this repo, recipe Y worked".

Skipped on purpose for now (until we have logged data to justify them):
SVM-style boundary detection, HMM-style hidden state inference,
unsupervised clustering, ensemble-of-reviewers. Each can earn its slot
when spans give it training signal. Adding them today is a museum.

## Decision

Tern's intelligence is decomposed into three cooperating subsystems —
`router`, `recall`, `curator` — each a separate src module, each landing as
its own session, each producing one new file family.

### 1) Per-turn cognitive router (S18)

`src/tern/router/`

- `classify(prompt, ctx) -> Purpose` — heuristic-first, LLM-fallback.
  - Regex pass: keywords like `review`, `architecture`, `refactor`,
    `lint`, `rename`, `boilerplate` → fast purpose label.
  - Miss: one Nova Micro call (~$0.0001) returns label.
- `route(purpose, ctx) -> model_id` — uses ADR-0004's
  `_MODEL_FOR_PURPOSE` map; `tern config set route.<purpose> <model_id>` overrides.
- Every classification + routing decision becomes a `RoutingSpan` event,
  feeding S19's curation queue. We grow our own dataset.

CLI surface stays the same: `tern run "..."`. `--model` still wins; absent
`--model`, the router fires.

### 2) Per-repo similarity recall (S18, same session as router)

`src/tern/recall/`

- Embeddings over `prompt_text` of every assistant turn span, stored at
  `~/.tern/projects/<sanitized>/recall/index.<sha>.npz`.
- Provider: Bedrock Titan Embeddings v2 (cheap, no new dep).
- On a new turn, before the LLM call: pull top-3 similar past turns from
  THIS repo, prepend the canonical reply + outcome to the system prompt
  under a `══ SIMILAR PAST TURNS ══` banner.
- Banner shape mirrors S15 memory banners (same compose pipeline).
- `tern recall <prompt>` CLI surface for human inspection.

### 3) Curator + Bayesian priors (S19)

`src/tern/memory/curate.py` already exists (v0). Extend:

- Curator pass reads `~/.tern/memory/curation_queue.jsonl` (S15 already
  populates if `TERN_AUTO_CURATE=1`) **plus** outcome spans (commit hash
  landed? tests passed? user corrected next turn?).
- Distill into `<repo>/.tern/memory/{ARCH,DECISIONS,FAILURES,REVIEWERS}.md`
  diff proposals. User accepts via `tern curate` like a PR review.
- Bayesian prior is implicit: entries that get accepted survive; entries
  that don't get pruned next pass. No explicit P(X|Y) math. The store's
  long-tail accumulation IS the prior.

## Alternatives considered

- **Ensemble of reviewers as random forest** — already trivially expressible
  as one prompt with multiple personas. No infra warranted.
- **Vector search over everything (no decision tree)** — pure KNN with no
  classification. Wastes context window on irrelevant similar turns. Tree
  pre-filters by purpose, then KNN within bucket.
- **Heavy router (always-LLM classification)** — costs $0.0001 × every turn.
  Heuristic-first stays free for the boring 70%, LLM only on miss.
- **Random Forest / SVM / HMM today** — no logged span data yet. Premature.

## Consequences

- New module families: `router/`, `recall/`. New ADR (this one), new tests.
- One new dependency: `numpy` for vector ops (already transitive via boto3).
- Per-turn cost goes **down** on average (cheap routes use Nova/Haiku) and
  **up** on architecture/security turns (Opus is right for those). Banner
  cost line still shows real $.
- Spans now include `routing_decision` and `recall_hits`. Recorder schema
  bumps. ADR-0002 (state replaced each turn) still holds — recall is
  injected into the system prompt of the new turn, not mutated into history.
- Mode = "yolo" can disable the LLM-fallback classifier (trust regex only)
  for ultra-cheap CI loops.

## Sequencing (locked unless contradicted)

- **S17** — repo-scoped memory tier (Layer A substrate). The
  `<repo>/.tern/memory/{ARCH,DECISIONS,FAILURES,REVIEWERS}.md` files,
  banner injection when running inside a repo, `MemoryTool` gets
  `scope: "global" | "repo"`. **Tomorrow.**
- **S18** — router + recall (this ADR's first two subsystems).
- **S19** — curator extends to outcome spans (this ADR's third subsystem).
- **S20** — StackOverflow lookup on error spans (now justified — we have
  failure data to search against).
- **S21+** — vision, browser-use polish. Deferred.

## Open questions for future sessions

- Embedding model cache: per-repo or per-user? Default per-repo so a
  rename/move doesn't pollute. Re-evaluate after S18 ships.
- Recall bucket key: purpose label only, or `(purpose, file-extension)`?
  Lean toward purpose-only for v0; add file-ext if recall precision low.
- Outcome ground-truth signal: git log + pytest exit + user "looks good" /
  "no, try again". Codify in S19.
