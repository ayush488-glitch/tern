"""SKILL.md catalog — discovery, parsing, digest rendering.

Source-of-truth lives on disk: every directory under
`~/.tern/skills/<name>/` and `.tern/skills/<name>/` containing a `SKILL.md`
becomes a Skill. Project-level skills shadow user-level ones on name
collision (closer to the work wins).

Frontmatter is a tiny YAML subset. We parse it without pulling in PyYAML —
flat key:value pairs plus optional bracket-list values. That's enough for
`name`, `description`, `when_to_use`, and `allowed_tools`.

Why not full YAML? We control the format, validation should be loud, and the
extra dependency buys nothing. claude-code's loadSkillsDir does the same
thing with a hand-rolled parser; we follow suit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from tern.obs.paths import tern_home


@dataclass(frozen=True, slots=True)
class Skill:
    """A discovered SKILL.md.

    `body` is the markdown content stripped of frontmatter. `source` is
    `"user"` or `"project"` so callers can show provenance (and so tests can
    assert shadowing works).
    """

    name: str
    description: str
    when_to_use: str
    allowed_tools: tuple[str, ...]
    body: str
    path: Path
    source: str  # "user" | "project"

    # Keyword index, computed once: name + description + when_to_use + body,
    # lowercased and tokenized. Used by the retrieval layer.
    keywords: frozenset[str] = field(default_factory=frozenset)


# ---- frontmatter parsing -------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """Return (frontmatter, body). Frontmatter is the leading `---`-fenced
    YAML block; body is everything after. If no frontmatter is present, the
    skill is rejected upstream (the caller decides — we just return {} here).
    """
    lines = text.splitlines(keepends=False)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        # Unterminated frontmatter: treat the whole thing as body.
        return {}, text

    fm: dict[str, str | list[str]] = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, sep, val = raw.partition(":")
        if not sep:
            continue
        k = key.strip()
        v = val.strip()
        # Strip matching quotes.
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        # Bracketed list: [a, b, c]
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            items = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            fm[k] = items
        else:
            fm[k] = v
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return fm, body


def _tokenize(*texts: str) -> frozenset[str]:
    """Crude but effective: lowercase, split on non-alnum, drop short tokens."""
    out: set[str] = set()
    for t in texts:
        for word in "".join(c if c.isalnum() else " " for c in t.lower()).split():
            if len(word) >= 3:
                out.add(word)
    return frozenset(out)


def _parse_skill_file(path: Path, source: str) -> Skill | None:
    """Parse one SKILL.md. Returns None on malformed files (and prints a
    breadcrumb) — one bad skill must not break the whole catalog."""
    try:
        text = path.read_text("utf-8")
    except OSError:
        return None
    fm, body = _parse_frontmatter(text)
    name = fm.get("name") or path.parent.name
    desc = fm.get("description") or ""
    when = fm.get("when_to_use") or ""
    tools_raw = fm.get("allowed_tools") or []
    if isinstance(name, list) or isinstance(desc, list) or isinstance(when, list):
        return None
    if not isinstance(tools_raw, list):
        tools_raw = [tools_raw] if tools_raw else []
    return Skill(
        name=str(name),
        description=str(desc),
        when_to_use=str(when),
        allowed_tools=tuple(str(t) for t in tools_raw),
        body=body,
        path=path,
        source=source,
        keywords=_tokenize(str(name), str(desc), str(when), body),
    )


# ---- discovery -----------------------------------------------------------


def _user_skills_dir() -> Path:
    """Honors TERN_HOME so tests can isolate. Lives next to the object store."""
    return tern_home() / "skills"


def _project_skills_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / ".tern" / "skills"


def _scan(dir_: Path, source: str) -> list[Skill]:
    if not dir_.is_dir():
        return []
    out: list[Skill] = []
    for child in sorted(dir_.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        skill = _parse_skill_file(skill_file, source)
        if skill is not None:
            out.append(skill)
    return out


def load_skills(cwd: Path | None = None) -> tuple[Skill, ...]:
    """Discover all skills. Project-level overrides user-level on name collision.

    Order: user skills first, then project skills overwrite by name.
    Final tuple is sorted by name for stable digest output.
    """
    if os.environ.get("TERN_DISABLE_SKILLS") == "1":
        return ()
    by_name: dict[str, Skill] = {}
    for s in _scan(_user_skills_dir(), "user"):
        by_name[s.name] = s
    for s in _scan(_project_skills_dir(cwd), "project"):
        by_name[s.name] = s
    return tuple(sorted(by_name.values(), key=lambda s: s.name))


# ---- system-prompt rendering --------------------------------------------


def catalog_digest(skills: tuple[Skill, ...]) -> str:
    """One-liner per skill — the cheap layer that ships in the system prompt
    every turn. Tells the model what's available without paying for bodies.
    """
    if not skills:
        return ""
    lines = ["AVAILABLE SKILLS (cite by name; ask if unsure):"]
    for s in skills:
        line = f"  - {s.name}: {s.description}"
        if s.when_to_use:
            line += f"  [when: {s.when_to_use}]"
        lines.append(line)
    return "\n".join(lines)


def render_active_block(active: tuple[Skill, ...]) -> str:
    """Full body of skills selected for this turn. Only paid for when the
    retrieval layer says they're relevant."""
    if not active:
        return ""
    parts = []
    for s in active:
        parts.append(f"### SKILL: {s.name}\n{s.body.strip()}")
    return "ACTIVE SKILLS — follow these procedures:\n\n" + "\n\n".join(parts)


def build_system_prompt(
    skills: tuple[Skill, ...],
    active: tuple[Skill, ...],
    *,
    base: str = "",
    include_memory: bool = True,
    cwd: Path | None = None,
    recall_hits: list[object] | None = None,
) -> str:
    """Compose: base preamble + catalog digest + active bodies + memory banners.

    Empty parts are dropped so a no-skills + no-memory run stays empty.

    `include_memory=True` (default) appends all four memory tiers:
      1. global MEMORY.md (your personal notes)
      2. repo-scoped memory (.tern/memory/ARCH|DECISIONS|FAILURES|REVIEWERS)
      3. SIMILAR PAST TURNS (KNN recall hits — S18)
      4. USER.md (user profile)
    Tests that don't want memory bleed-through can opt out with include_memory=False.
    `cwd` is forwarded to repo detection; defaults to Path.cwd() when None.
    `recall_hits` is a list[RecallHit] injected by the caller after a recall query.
    """
    chunks = []
    if base.strip():
        chunks.append(base.strip())
    digest = catalog_digest(skills)
    if digest:
        chunks.append(digest)
    block = render_active_block(active)
    if block:
        chunks.append(block)
    if include_memory:
        # local import to avoid a cycle if memory ever imports skills
        from tern.memory.store import render_all_banners_with_repo

        banners = render_all_banners_with_repo(cwd, recall_hits=recall_hits)
        if banners:
            chunks.append(banners)
    return "\n\n".join(chunks)
