"""Persistent memory — Hermes-shaped MEMORY.md + USER.md split (S15).

Two files under ~/.tern/memory/:
  - MEMORY.md   — procedural notes the agent writes for itself
  - USER.md     — identity / preferences about the user

Both are entry-separated by a single line containing only `§`. Each entry
is plain markdown. Loaded once per session, injected into the system prompt
under `══ MEMORY ══` / `══ USER PROFILE ══` banners. The agent edits via
the `memory` tool (actions: add | replace | remove).

Caps are warnings, not hard limits — over-cap triggers a banner the agent
sees so it can curate. The cap shape mirrors the Hermes contract:
~2200 chars MEMORY, ~1375 chars USER.
"""

from __future__ import annotations

from tern.memory.store import (
    MEMORY_CAP,
    USER_CAP,
    MemoryFile,
    add_entry,
    load_memory,
    memory_path,
    remove_entry,
    render_banner,
    replace_entry,
    user_path,
)

__all__ = [
    "MEMORY_CAP",
    "USER_CAP",
    "MemoryFile",
    "add_entry",
    "load_memory",
    "memory_path",
    "remove_entry",
    "render_banner",
    "replace_entry",
    "user_path",
]
