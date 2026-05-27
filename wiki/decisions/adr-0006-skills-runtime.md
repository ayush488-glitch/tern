---
title: ADR-0006 — Skills runtime (D2)
type: decision
created: 2026-05-28
updated: 2026-05-28
tags: [tern, skills, retrieval, system-prompt, d2]
---

# ADR-0006 — Skills as a first-class on-disk knowledge layer

## Context

D2 in the JTBD scope is "skills as first-class". Tern needs a way to teach the
model recurring procedures (code review, deploy, tone rules, library quirks)
without baking them into a system prompt or shipping them as MCP servers.

Existing patterns we lifted from:

- claude-code's `loadSkillsDir` — frontmatter + body, discovered from disk,
  user vs project layers.
- goose's `agents/skills/` — same layout convention, project shadows user.
- token-cost-master (already running for Ayush) — keep the cheap path cheap;
  pay tokens only when a skill is relevant.

## Decision

Skills are directories on disk containing a `SKILL.md` (YAML frontmatter +
markdown body). Two roots, scanned at session start and every turn:

1. `~/.tern/skills/<name>/SKILL.md`     user-global (honors `TERN_HOME`)
2. `<cwd>/.tern/skills/<name>/SKILL.md` project-local (wins on collision)

Frontmatter keys (all optional except `name`):

```yaml
name: code-review
description: Pre-commit code review checklist
when_to_use: When the user asks to review a diff or PR
allowed_tools: [read_file, edit_block]
```

Two layers cohabit in the system prompt:

- **Catalog digest** — one line per skill (`- name: description [when: …]`).
  Always shipped. Cheap (≈200 tokens for a dozen skills).
- **Active block** — full body of skills selected for *this turn only*.
  Rendered under `### SKILL: <name>`.

Per-turn retrieval has two signals (priority order):

1. **Explicit mention.** Regexes match `use the X skill`, `follow X skill`,
   `apply X skill`, `skill: X`. Always honored.
2. **Keyword overlap.** Same `_tokenize` function indexes prompt + skill;
   skills with overlap ≥ 2 tokens are picked, top-3 by score.

Hard cap of 3 active skills per turn. Beyond that the catalog/active split
stops paying for itself.

## Alternatives considered

- **Embeddings retrieval.** Rejected for S11. Overlap on bag-of-words is
  deterministic, has zero infra cost, and the roadmap explicitly says "start
  dumb: keyword match". Embeddings can replace the scorer later without
  changing anything else.
- **MCP-as-skills.** That's D6, not D2. Skills are flat markdown so a human
  can grep and edit them; MCP servers are runtime tools. Different shape.
- **Auto-load every skill into system prompt.** Trivial to implement, breaks
  the cost story the moment skills grow past three.
- **PyYAML for frontmatter.** Pulled in for ~5 keys we control. Hand-rolled
  parser is 30 LOC and rejects malformed input loudly.

## Consequences

Good:
- Skills work for every session with no config — drop a directory, it's live.
- Catalog digest tells the model what's available even when nothing's active,
  so it can ask ("which skill would you like me to follow?").
- Retrieval is pure: same `(prompt, skills)` → same active set. Replay-with-
  skills is deterministic for free.
- Bedrock adapter already lifts `role="system"` messages to the top-level
  `system` field, so we ship skills via a system message and nothing in the
  adapter or store needs to change.

Bad / accepted:
- A user with 50+ user-global skills pays ~1k tokens/turn for the catalog.
  Mitigation: `TERN_DISABLE_SKILLS=1` bypass; future work is per-project
  filtering.
- Keyword retrieval will miss synonyms ("ship" vs "deploy"). Acceptable for
  S11; users can keep using explicit mentions until the scorer improves.
- System messages remain prompts, not turn-objects. ADR-0005's
  `persist_message` still rejects them. Skills are reconstructed from disk
  at replay time, not stored alongside turn objects.

## Replay implications

Skills resolve at runtime from disk. Replay rebuilds the same active set
because retrieval is pure and the on-disk catalog is the source of truth.
This means a wiki-modified skill changes future behaviour but never
retroactively rewrites stored turn objects — exactly the property we want.
