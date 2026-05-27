---
title: S2 — grounding execution (clones, reads, architecture.html)
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [tern, session, grounding, architecture]
---

# S2 — grounding execution

Translated S1's decisions into on-disk artifacts: cloned reference repos, read the wiki broadly, synthesized into notes, produced the showpiece architecture HTML.

## What ran
- Cloned 5 reference repos into `.scratch/grounding/refs/` (gitignored): claude-code, aider, browser-use, mcp-python-sdk. (goose initially appeared to be a 19-file stub mid-clone but completed full at exit; minor signal — desktop UI + OIDC proxy, not the Rust agent core. Re-mine if S5 ADRs need it.)
- 3 wiki-deep-read syntheses delegated in parallel: llmops, security/reliability, storage-decoupling.
- 3 reference-repo extractions delegated in parallel: claude-code, aider, browser-use+MCP.
- Synthesis 1-pager + 6 detailed grounding notes written to `.scratch/grounding/notes/`.
- `docs/architecture.html` produced (~41KB, single file, pure b&w SVG, viewBox 1600×1900, six sections).

## Files produced
```
.scratch/grounding/refs/{claude-code, aider, browser-use, python-sdk, goose}
.scratch/grounding/notes/00-synthesis.md
.scratch/grounding/notes/01-wiki-llmops-synthesis.md
.scratch/grounding/notes/02-wiki-security-reliability.md
.scratch/grounding/notes/03-wiki-storage-decoupling.md
.scratch/grounding/notes/04-ref-claude-code.md
.scratch/grounding/notes/05-ref-aider.md
.scratch/grounding/notes/06-ref-browser-mcp.md
docs/architecture.html
```
Plus this session: AGENTS.md, full `wiki/` scaffold (index, log, roadmap, concepts, entities, sources, sessions). Rename antern→tern applied across all artifacts (no residue).

## Locks confirmed in S2
- The 14 modules (M0–M14) — see [14-modules](../concepts/14-modules.md).
- Build order: M11 first, then M0+M1+M4, then M5+M2, then M7 before M6/M8, then M9/M10, then M12/M13, then M14.
- Layer rules: arrows point inward toward canonical types and agent core.
- Five invariants preserved from prior art: turn loop = async generator, tools uniform, transcripts append-only JSONL, reflection retry loop, few-shot exemplar in system prompt.
- Three things Tern changes from prior art: textual not ink, runtime plugins not build-time flags, provider abstraction owned by cost router (litellm = ONE backend).

## Handoff to S3
Next session opens `wiki/index.md` → `wiki/roadmap/14-session-plan.md` → S3 row.
S3 = repo skeleton + first green commit. Files to create:
- `pyproject.toml` (uv-friendly, py3.12, pipx target name `tern`)
- `src/tern/__init__.py`, `src/tern/cli.py` (Typer or Click; smallest surface)
- `tests/test_smoke.py` (asserts version)
- `ruff.toml` or `[tool.ruff]` in pyproject
- `mypy.ini` or `[tool.mypy]` in pyproject
- README.md stub
- `git add -A && git commit -m "init: empty tern skeleton, green"`

Done state of S3: `tern --version` works, `pytest` green, first commit landed.
