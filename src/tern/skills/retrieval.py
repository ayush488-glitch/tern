"""Per-turn skill retrieval — pick which skills go into the active block.

Two signals (in priority order):

1. **Explicit mention.** If the user says "use the X skill" or "skill: X" or
   "follow X", that wins outright. Always honored. Mirrors goose's
   "Use the code-review skill to review this PR" and claude-code's
   `<skill>` directive.

2. **Keyword overlap.** Tokenize the user's prompt the same way we tokenize
   skill metadata, then score each skill by token-overlap. Anything past a
   small threshold is auto-activated. Crude bag-of-words on purpose: cheap,
   deterministic, no embedding service to keep alive. The roadmap promises
   "start dumb: keyword match"; this is that.

We deliberately cap active skills to 3 — beyond that the system prompt
bloats and the cost discipline that justifies the catalog/active split
breaks down.

The retrieval layer is pure: same prompt + same skills → same active set.
That makes replay-with-skills determinism free.
"""
from __future__ import annotations

import re

from tern.skills.catalog import Skill, _tokenize

_MAX_ACTIVE = 3
_MIN_OVERLAP = 2  # tokens shared between prompt and skill index
_MENTION_PATTERNS = (
    re.compile(r"\buse(?:\s+the)?\s+([a-z0-9][a-z0-9_\-]+)\s+skill\b", re.I),
    re.compile(r"\bfollow(?:\s+the)?\s+([a-z0-9][a-z0-9_\-]+)\s+skill\b", re.I),
    re.compile(r"\bskill[:\s]+([a-z0-9][a-z0-9_\-]+)", re.I),
    re.compile(r"\bapply(?:\s+the)?\s+([a-z0-9][a-z0-9_\-]+)\s+skill\b", re.I),
)


def _explicit_mentions(prompt: str, skills: tuple[Skill, ...]) -> list[Skill]:
    """Find skills the user named directly."""
    if not skills:
        return []
    by_name = {s.name.lower(): s for s in skills}
    hits: list[Skill] = []
    seen: set[str] = set()
    for pat in _MENTION_PATTERNS:
        for m in pat.finditer(prompt):
            key = m.group(1).lower()
            if key in by_name and key not in seen:
                seen.add(key)
                hits.append(by_name[key])
    return hits


def _score(prompt_tokens: frozenset[str], skill: Skill) -> int:
    """Token-overlap score between user prompt and skill index."""
    return len(prompt_tokens & skill.keywords)


def select_active(
    prompt: str,
    skills: tuple[Skill, ...],
    *,
    max_active: int = _MAX_ACTIVE,
    min_overlap: int = _MIN_OVERLAP,
) -> tuple[Skill, ...]:
    """Return the skills to include in this turn's active block.

    Always honors explicit mentions first; fills remaining slots by
    keyword-overlap score, descending. Stable order: explicit mentions in
    order of appearance, then alphabetical for ties in score.
    """
    if not skills:
        return ()
    explicit = _explicit_mentions(prompt, skills)
    explicit_names = {s.name for s in explicit}

    if len(explicit) >= max_active:
        return tuple(explicit[:max_active])

    prompt_tokens = _tokenize(prompt)
    scored: list[tuple[int, str, Skill]] = []
    for s in skills:
        if s.name in explicit_names:
            continue
        sc = _score(prompt_tokens, s)
        if sc >= min_overlap:
            scored.append((sc, s.name, s))
    scored.sort(key=lambda r: (-r[0], r[1]))

    remaining = max_active - len(explicit)
    keyword_picks = [s for _, _, s in scored[:remaining]]
    return tuple([*explicit, *keyword_picks])
