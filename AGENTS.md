# AGENTS.md — Tern project wiki schema

This file is read by every coding-agent session working on Tern.
It tells the agent how the wiki is structured, how to ingest, query, and lint,
and which workflows to follow.

If this file and the wiki disagree, this file wins. Update this file deliberately;
the wiki follows.

---

## What Tern is
Tern is a Python CLI coding agent in the spirit of Claude Code, with six baked-in
differentiators: per-turn cost routing (D1), skills as first-class (D2), per-turn
replay/branch (D3), live HTML notes artifact (D4), browser-use as a real tool (D5),
MCP client built-in (D6).

Open-source foundation. Ayush Singh / Antern company. Python 3.12, pipx-installable.

---

## Three layers

```
raw/                    immutable source of truth — articles, papers, transcripts, clones
wiki/                   LLM-maintained markdown — the compiled knowledge
  index.md              content catalog (read first when answering)
  log.md                chronological append-only ops log
  sources/              one page per ingested source (1:1 with raw/)
  entities/             people, projects, libraries, repos
  concepts/             ideas, patterns, primitives
  decisions/            ADRs — context · decision · alternatives · consequences
  roadmap/              phase plans, sessions, milestones
  sessions/             per-session handoff notes (chronological)
  assets/               images downloaded from sources
AGENTS.md               this file (the schema)
.scratch/               LOCAL-ONLY scratch (gitignored) — clones, raw notes
docs/                   shipped artifacts (architecture.html, notes.html)
src/, tests/, etc.      the product itself
```

`raw/` and `wiki/` are immutable in opposite ways: `raw/` is never modified by the
agent (read-only source of truth); `wiki/` is owned entirely by the agent (humans
read, agent writes).

---

## Conventions

### Page frontmatter
Every wiki page (except `index.md` and `log.md`) starts with YAML frontmatter:

```yaml
---
title: <human title>
type: source | entity | concept | decision | roadmap | session
created: 2026-05-27
updated: 2026-05-27
sources: [sources/foo.md, sources/bar.md]   # for synthesis pages
tags: [tern, agent-loop, ...]
---
```

### File names
- lowercase-kebab-case: `agent-turn-loop.md`, `cost-router.md`
- sources mirror the raw filename: `raw/aider-readme.md` → `wiki/sources/aider-readme.md`
- decisions: `wiki/decisions/adr-NNNN-short-name.md` (zero-padded, monotonic)

### Cross-references
Use relative links: `[turn loop](../concepts/agent-turn-loop.md)`.
Every concept page should be linked from at least two other pages — orphans get flagged in lint.

### Citations
When a wiki page makes a claim derived from a source, link the source page inline:
"State is replaced, not mutated ([claude-code](../sources/claude-code.md))".
Don't link to `raw/` directly — always via the source page.

---

## Operations

### INGEST
Trigger: user drops something in `raw/` and says "ingest" / "process".

Steps:
1. Read the source from `raw/`.
2. Discuss key takeaways with the user (one paragraph, then ask "anything I missed?").
3. Write `wiki/sources/<name>.md` — summary + key claims + raw-file pointer.
4. Update or create relevant `wiki/entities/`, `wiki/concepts/`, `wiki/decisions/` pages.
   A single source typically touches 5–15 wiki pages. Cross-reference both ways.
5. Update `wiki/index.md` with the new source and any new entity/concept pages.
6. Append to `wiki/log.md`:
   `## [YYYY-MM-DD] ingest | <source title> | touched: N pages`
7. Commit: `wiki: ingest <source>`.

### QUERY
Trigger: user asks a question about the project / domain.

Steps:
1. Read `wiki/index.md` first.
2. Drill into relevant pages (concepts, entities, decisions, sessions).
3. Synthesize answer with citations to wiki pages (not raw/).
4. If the answer is non-trivial and reusable, file it as a new wiki page (typically under
   `concepts/` or `decisions/`) and update `index.md`. Append to `log.md`:
   `## [YYYY-MM-DD] query | <question> | filed: <new-page>`
5. If the question revealed a gap, suggest sources to ingest or sub-questions to investigate.

### LINT
Trigger: user says "lint wiki" / weekly cadence / before a phase boundary.

Steps:
1. Find contradictions between pages (claim X in A, contradicting claim in B).
2. Find stale claims that newer sources have superseded.
3. Find orphan pages (no inbound links).
4. Find concepts mentioned in 3+ pages without their own page.
5. Find missing cross-references.
6. Suggest sources / web searches to fill gaps.
7. Apply mechanical fixes; surface judgment calls to the user.
8. Append to `log.md`: `## [YYYY-MM-DD] lint | findings: N | applied: M`.

### SESSION HANDOFF (Tern-specific)
At the END of every working session (not just on /compact):
1. Write `wiki/sessions/SNN-<topic>.md` — what was decided, what was built, what's next.
2. Update `wiki/roadmap/14-session-plan.md` — mark current session done, point at next.
3. Update `wiki/index.md` if any new top-level pages exist.
4. Append to `wiki/log.md`: `## [YYYY-MM-DD] session-end | SNN <topic>`.
5. Final commit: `session: SNN <topic>`.

At the START of every working session:
1. Read this file (AGENTS.md).
2. Read `wiki/index.md`.
3. Read `wiki/roadmap/14-session-plan.md` to find current session.
4. Read the most recent `wiki/sessions/SNN-*.md` for handoff context.
5. Then proceed with the user's request.

---

## Index discipline

`wiki/index.md` is the agent's primary entry point. It must:
- list every page in the wiki, grouped by type (sources, entities, concepts, decisions, roadmap, sessions)
- one-line summary per page
- be updated on every ingest / query-filed / session-end / decision

Think of `index.md` as the README of the brain.

---

## Log discipline

`wiki/log.md` is append-only. Every line a heading starts with `## [YYYY-MM-DD]`.
Entry types: `ingest | query | lint | session-end | decision | milestone`.
Useful: `grep "^## \[" wiki/log.md | tail -20` to see what just happened.

---

## What this wiki is NOT
- Not a place for product code (that's `src/tern/`).
- Not a place for shipped artifacts (those are in `docs/`).
- Not a substitute for tests (the wiki documents intent; tests verify behavior).
- Not a place for transient notes (use `.scratch/` for things you don't want to keep).

---

## Tone for wiki pages
Senior-engineer thinking out loud. Short sentences. Plain English. No em dashes — use
parens, commas, "so", "because". Avoid leverage / robust / facilitate. Name the failure
mode before the fix. Decisions are Ayush's, not "the agent's".

This is the same teaching/explain voice from the user profile, applied to engineering writing.
