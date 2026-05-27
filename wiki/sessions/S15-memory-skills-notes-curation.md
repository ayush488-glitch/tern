---
title: S15 — memory · skills self-management · notes_append fix · self-curation v0
type: session
created: 2026-05-28
updated: 2026-05-28
tags: [s15, memory, skill-manage, notes-append, self-curation]
---

# S15 — handoff

## Built (~90 min)

**Memory store** (`src/tern/memory/`):
- `store.py` — load/save MEMORY.md + USER.md, atomic writes, `§` separator,
  cap warnings (2200/1375 chars), banner rendering.
- `__init__.py` — public surface.
- `curate.py` — self-curation v0: heuristic nudge queue gated on
  `TERN_AUTO_CURATE=1`. Writes JSONL hints, never auto-edits memory files.

**Native tools**:
- `memory_tool.py` — `memory(action=add|replace|remove, target=memory|user, ...)`.
  Mirrors Hermes contract.
- `skill_manage.py` — `skill_manage(action=create|patch|edit|delete|write_file|remove_file,
  name, scope=user|project, ...)`. Restricts file writes to
  references/templates/scripts/assets prefixes.

**System prompt**:
- `skills/catalog.build_system_prompt` now appends MEMORY/USER banners
  (toggleable via `include_memory=False` for tests).

**notes_append fix**:
- Tightened description: explicit instruction to use structured tool calls,
  not literal XML.
- Canonical-layer rescue parser `core.canonical.lift_pseudo_xml_tool_calls`:
  promotes `<tool_name>...</tool_name>` text-blocks into synthetic
  ToolCallBlocks with id `rescue_<uuid>`. Scoped to the registered tool
  list (won't grab arbitrary prose). Idempotent.
- Loop calls it right after the provider response, before tool-call
  extraction.

**Registry wiring**: MemoryTool + SkillManageTool registered in both
`cli.py` (run command) and `ui/app.py` (REPL).

## Demoable

Round-trip across sessions:
```
TERN_LIVE=1 TERN_HOME=/tmp/tern-s15 tern run \
  "Use the memory tool to add 'prefers concise replies' to user memory."
# → memory entry added

TERN_LIVE=1 TERN_HOME=/tmp/tern-s15 tern run \
  "what do you know about my preferences?"
# → "you prefer concise replies."
```

## Gates entering S16

- pytest **260/260** ✅ (was 210; +50 new)
- ruff ✅
- mypy --strict ✅ (47 src files; was 18)
- live Bedrock smoke ✅ (memory tool fires; banner re-injected next session)

## Pitfalls logged

- Pyright complains about Pydantic optional-field instantiation in tests —
  noise, not a real type error. mypy is src-only, doesn't trip on it.
- `asyncio.get_event_loop()` is removed in Python 3.10+ when no loop is
  running. Use `asyncio.run(coro)` in test helpers.
- Ruff RUF002 flags `×` (multiplication sign) in docstrings. Use plain
  `x` for documentation.

## Next: S16

Per `wiki/roadmap/14-session-plan.md` — model breadth (more Bedrock
families) + first-class image inputs.
