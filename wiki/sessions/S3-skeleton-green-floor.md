---
title: S3 — repo skeleton, first green commit
type: session
created: 2026-05-27
updated: 2026-05-27
tags: [tern, session, skeleton, green-floor]
---

# S3 — repo skeleton + first green commit

The session that turned design into code. Ships nothing the user sees yet beyond `tern --version`, but locks in the toolchain so every subsequent session has a green floor to stand on.

## What got built
- `pyproject.toml` — Hatchling backend, `tern` script entry, `[dev]` extras = pytest+ruff+mypy.
- `src/tern/__init__.py` — `__version__ = "0.0.1"`.
- `src/tern/cli.py` — Typer app. `tern --version` and `tern version`. Help on no-args.
- `tests/test_smoke.py` — 3 tests: version constant, --version flag, version subcommand.
- `tests/__init__.py`
- `README.md` — install + run + pointers to `AGENTS.md`, `docs/architecture.html`, `wiki/index.md`.
- `.gitignore` — `.scratch/`, venv, mypy/ruff/pytest caches.

## Four gates green
```
tern --version            → tern 0.0.1
tern version              → tern 0.0.1
pytest -q                 → 3 passed
ruff check src tests      → All checks passed!
mypy --strict src         → no issues found in 2 source files
```

## First commit
`38878b6 init: empty tern skeleton, green` (28 tracked files; `.scratch/` correctly excluded from `git ls-files`).

## Decisions taken in S3
- **CLI framework**: Typer (over Click). Type-hint-driven, less ceremony, plays well with strict mypy. Future-proof for adding `run / log / resume / branch` commands.
- **Output**: rich Console (over print). Already a dep via Typer; gives us the formatting story for free.
- **Python floor**: 3.10 (not 3.12). Breadth on user machines matters more than 3.12-only features at v1. Aider supports back to 3.10 too. Locks `target-version = "py310"` in ruff.
- **Build backend**: Hatchling (over setuptools). Modern, no `setup.py` weirdness, clean `pyproject.toml`-only project.
- **Strict mypy from day 1**. Cheaper to keep clean than retrofit.
- **No `BaseSomething` abstractions yet**. Resist adding scaffolding before there's a second concrete thing demanding shared shape.

## Pitfalls hit (and the fixes)
- **Typer `--version` callback**: needed `invoke_without_command=True` AND `is_eager=True` on the Option, AND the callback raises `typer.Exit()`. Without that combo, `tern --version` errors with "Missing command". Now: also prints help with non-zero exit when run with no args, which is the right shape.
- **Old pip in `python3.10 -m venv`**: the bundled pip was 21.x and refused to install editable from a `pyproject.toml`-only project. Fix: `python -m pip install --upgrade pip` after activating, then editable install works.

## Handoff to S4
Next session = S4: Phase 0 — JTBD + scope. File `wiki/decisions/adr-0001-jtbd-and-scope.md`. Format: context · decision · alternatives · consequences. Drafts the user / job / success criteria / what-it-isn't / anti-scope / week-1/2/4 demo-visibility milestones.

Then S5: 4 ADRs for architecture sub-picks (runtime, tool surface, provider, session/state).

After S5 the design is locked end-to-end and Stage II implementation (S6+) can run cleanly.

## How a future session resumes from here
1. Read `AGENTS.md`.
2. Read `wiki/index.md`.
3. Read `wiki/roadmap/14-session-plan.md` — find next session marker `▶`.
4. Read this session's `wiki/sessions/SNN-*.md`.
5. Run gates: `pytest && ruff check src tests && mypy src` (all should be green; if not, restore green before doing anything else).
6. Then start the next session.
