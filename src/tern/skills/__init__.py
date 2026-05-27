"""S11 / D2 — skills runtime.

Disk-discovered SKILL.md files become a routable knowledge layer the agent
references on demand.

Layout (per ADR-0006):

  ~/.tern/skills/<name>/SKILL.md    user-global
  .tern/skills/<name>/SKILL.md      project-local (wins on collision)

A SKILL.md file is YAML frontmatter + markdown body:

    ---
    name: code-review
    description: Pre-commit code review checklist
    when_to_use: When the user asks to review a diff, PR, or commit.
    allowed_tools: [read_file]
    ---

    # Body

    ...

The runtime never auto-loads bodies into the system prompt. At session start
it injects only a *catalog digest* (one line per skill: name + description).
Per-turn retrieval — keyword match on the user's prompt or an explicit
"use the X skill" mention — escalates a skill to "active" and its full body
is appended to the system prompt for that turn only.

This keeps the cheap path cheap (a 200-token catalog instead of 20,000-token
bodies) while making skills first-class enough that the model can reach for
one when it actually matters. Mirrors the cost discipline in
token-cost-master and the "skills as filesystem entries" pattern from
claude-code's loadSkillsDir + goose's agents/skills/.
"""
from __future__ import annotations

from tern.skills.catalog import (
    Skill,
    build_system_prompt,
    catalog_digest,
    load_skills,
    render_active_block,
)
from tern.skills.retrieval import select_active

__all__ = [
    "Skill",
    "build_system_prompt",
    "catalog_digest",
    "load_skills",
    "render_active_block",
    "select_active",
]
