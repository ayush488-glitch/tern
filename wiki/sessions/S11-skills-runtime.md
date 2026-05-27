---
title: S11 — skills runtime (D2)
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [tern, session, s11, skills, d2]
---

# S11 — skills runtime (D2)

~75 min. Shipped end-to-end. Live Bedrock smoke green twice (explicit mention
and keyword-overlap paths both activate the right skill and the model obeys).

## What got built

`src/tern/skills/`
- `catalog.py` — `Skill` dataclass, hand-rolled frontmatter parser, disk
  discovery (`load_skills`), digest renderer, active-block renderer,
  composite `build_system_prompt`. Honors `TERN_HOME` for user skills and
  `TERN_DISABLE_SKILLS=1` to short-circuit the whole layer.
- `retrieval.py` — `select_active(prompt, skills)`. Two signals: explicit
  mentions (regex on `use the X skill` / `follow X skill` / `skill: X` /
  `apply the X skill`), then keyword overlap with the prompt. Cap 3.

`src/tern/cli.py`
- `tern run` and `tern resume` build a system message from skills and
  prepend it to `Turn.messages`. Adapter already lifted system messages,
  so the adapter and store needed zero changes.
- `tern skills` lists discovered skills with provenance.
- `tern skills show <name>` prints the full body.

`src/tern/ui/app.py`
- Inline REPL re-runs retrieval each turn (the user prompt drives it),
  prints `· skills active: x, y` as a one-liner before streaming starts.

`tests/test_skills.py`
- 17 tests: frontmatter parsing (3), discovery + project-shadows-user (5),
  digest/active rendering (4), retrieval (5).

## Gates

- pytest **125/125** green (was 108/108 entering S11; +17).
- ruff clean.
- mypy --strict clean (31 src files).
- `tern --version` ✅.
- live Bedrock smoke ✅:
  - explicit: `tern run "use the three-words skill and describe the sky"`
    → `blue endless expanse`
  - keyword: `tern run "describe the ocean briefly in three words"`
    → `vast blue depths`

## Decisions made

- Hand-rolled frontmatter parser over PyYAML — no new dep for ~5 keys.
- Skills shipped as one `system` message; adapter lifts it. No turn-object
  changes (system messages stay rejected by `persist_message`, per
  ADR-0005).
- Cap at 3 active per turn; threshold of 2 shared tokens for keyword match.
- Project skills under `<cwd>/.tern/skills/`, user skills under
  `~/.tern/skills/`. Project wins on collision.
- Demo skill committed at `.tern/skills/three-words/SKILL.md` so the smoke
  test reproduces from a clean checkout.

## Pitfalls hit + logged

- First wiring tried `from tern.skills import build_system_prompt` before
  `__init__.py` re-exported it; mypy caught it instantly. Fixed by adding
  to `__all__` and importing directly from `tern.skills.catalog` in cli.py
  (less indirection).
- Initial `_user_skills_dir()` placement matters: it must call
  `tern_home()` lazily (function call, not module-level constant), or
  `monkeypatch.setenv("TERN_HOME", …)` in tests has no effect. Got this
  right first time because we copied the pattern from `obs/paths.py`.

## Next: S12

D4 — live HTML notes artifact. `notes_append` + `notes_render`. Reads turn
objects (M7 already done in S10), writes `docs/notes.html` each turn. Same
b&w aesthetic as `architecture.html`. ~75 min.
