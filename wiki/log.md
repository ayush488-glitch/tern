# Tern — ops log

Append-only. Newest at the bottom. Every entry starts with `## [YYYY-MM-DD]`.

Types: `ingest | query | lint | session-end | decision | milestone | rename`.

---

## [2026-05-27] milestone | grounding complete
Cloned 5 reference repos. 3 wiki-deep-read syntheses + 3 reference-repo extractions. 6 differentiators locked. 14 modules named. One-page b&w architecture artifact at docs/architecture.html.

## [2026-05-27] decision | name = tern
Originally proposed `antern`, user picked `tern`. Shorter, ergonomic CLI binary, still ties to Antern brand without being a literal substring.

## [2026-05-27] rename | antern → tern
Applied across .scratch/grounding/notes/* and docs/architecture.html. No residue.

## [2026-05-27] milestone | S3 — repo skeleton, first green commit
pyproject.toml + src/tern/{__init__,cli}.py + tests/test_smoke.py. Four gates green: `tern --version`, `pytest` (3/3), `ruff check`, `mypy --strict`. Commit 38878b6 landed on a clean tree (28 tracked files; `.scratch/` correctly excluded). Stack: typer + rich; py3.10 floor for breadth.

## [2026-05-27] milestone | LLM Wiki bootstrapped
AGENTS.md schema, wiki/index.md, wiki/log.md, wiki/roadmap/14-session-plan.md, wiki/concepts/, wiki/entities/, wiki/sources/, wiki/sessions/ scaffolded. Pattern: ingest / query / lint / session-handoff. This wiki is now THE persistent memory across sessions.
