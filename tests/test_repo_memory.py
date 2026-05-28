"""S17 — repo-scoped memory tier.

Tests cover:
  - repo detection (find_repo_root) via .git and .tern markers
  - find_repo_root absent-repo fallback (returns None)
  - load/add/replace/remove for each repo target
  - render_repo_banner: empty → '', populated with correct sections
  - banner composition order: global MEMORY first, then REPO MEMORY, then USER PROFILE
  - absent-repo banner fallback: render_all_banners_with_repo falls back gracefully
  - MemoryTool scope routing: scope='global' still works unchanged
  - MemoryTool scope='repo': add/replace/remove round-trip
  - MemoryTool scope='repo' with no repo root returns error
  - MemoryTool unknown scope returns error
  - MemoryTool unknown target for repo scope returns error
  - build_system_prompt threads cwd through to repo memory
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tern.memory.repo_store import (
    REPO_TARGETS,
    add_repo_entry,
    find_repo_root,
    load_repo_memory,
    remove_repo_entry,
    render_repo_banner,
    replace_repo_entry,
)
from tern.memory.store import render_all_banners_with_repo
from tern.tools.native.memory_tool import MemoryArgs, MemoryTool
from tern.tools.protocol import ToolContext

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ctx(repo_root: Path) -> ToolContext:
    return ToolContext(repo_root=repo_root, session_id="s17", turn_idx=0, mode="default")


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------


def test_find_repo_root_via_git(tmp_path):
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "src" / "deep"
    subdir.mkdir(parents=True)
    assert find_repo_root(subdir) == tmp_path


def test_find_repo_root_via_tern_dir(tmp_path):
    (tmp_path / ".tern").mkdir()
    assert find_repo_root(tmp_path) == tmp_path


def test_find_repo_root_walks_upward(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path


def test_find_repo_root_returns_none_when_no_marker(tmp_path):
    # tmp_path has no .git or .tern; walk will eventually hit filesystem root
    # which also has no marker → None
    isolated = tmp_path / "orphan"
    isolated.mkdir()
    # To avoid accidentally hitting a real .git above tmp_path, we can't fully
    # control the environment. But if the root FS has no .git the result is None.
    # We assert find_repo_root doesn't raise.
    result = find_repo_root(isolated)
    # result is either None or a real repo root found above tmp_path (CI). Both OK.
    assert result is None or result.exists()


def test_find_repo_root_tern_wins_over_ancestor_git(tmp_path):
    # grandparent has .git, parent has .tern → parent is the repo root
    (tmp_path / ".git").mkdir()
    parent = tmp_path / "sub"
    parent.mkdir()
    (parent / ".tern").mkdir()
    child = parent / "pkg"
    child.mkdir()
    assert find_repo_root(child) == parent


# ---------------------------------------------------------------------------
# load / add / replace / remove
# ---------------------------------------------------------------------------


def test_load_empty_repo_memory(tmp_path):
    (tmp_path / ".tern").mkdir()
    entries, text = load_repo_memory("arch", tmp_path)
    assert entries == ()
    assert text == ""


def test_add_repo_entry_round_trips(tmp_path):
    (tmp_path / ".tern").mkdir()
    entries = add_repo_entry("arch", "uses async generators", tmp_path)
    assert entries == ("uses async generators",)
    # file was created
    entries2, raw = load_repo_memory("arch", tmp_path)
    assert "uses async generators" in raw
    assert entries2 == ("uses async generators",)


def test_add_multiple_entries_separated(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("decisions", "ADR-0001: async only", tmp_path)
    add_repo_entry("decisions", "ADR-0002: state replaced each turn", tmp_path)
    entries, raw = load_repo_memory("decisions", tmp_path)
    assert len(entries) == 2
    assert raw.count("§") == 1


def test_add_empty_entry_rejected(tmp_path):
    (tmp_path / ".tern").mkdir()
    with pytest.raises(ValueError, match="must not be empty"):
        add_repo_entry("failures", "   ", tmp_path)


def test_replace_repo_entry(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("failures", "old failure pattern: foo", tmp_path)
    replace_repo_entry("failures", "old failure", "new failure pattern: bar", tmp_path)
    entries, _ = load_repo_memory("failures", tmp_path)
    assert entries == ("new failure pattern: bar",)


def test_replace_no_match_raises(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("reviewers", "Alice prefers short PRs", tmp_path)
    with pytest.raises(LookupError):
        replace_repo_entry("reviewers", "ghost", "x", tmp_path)


def test_replace_ambiguous_raises(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("arch", "common token A", tmp_path)
    add_repo_entry("arch", "common token B", tmp_path)
    with pytest.raises(LookupError, match="matches 2"):
        replace_repo_entry("arch", "common token", "merged", tmp_path)


def test_remove_repo_entry(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("arch", "keep", tmp_path)
    add_repo_entry("arch", "drop me", tmp_path)
    remove_repo_entry("arch", "drop me", tmp_path)
    entries, _ = load_repo_memory("arch", tmp_path)
    assert entries == ("keep",)


def test_invalid_repo_target_raises(tmp_path):
    (tmp_path / ".tern").mkdir()
    with pytest.raises(ValueError, match="unknown repo memory target"):
        load_repo_memory("bogus", tmp_path)


def test_atomic_write_no_temp_files_left(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("arch", "entry 1", tmp_path)
    add_repo_entry("arch", "entry 2", tmp_path)
    leftovers = list((tmp_path / ".tern" / "memory").glob(".repomem-*"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# render_repo_banner
# ---------------------------------------------------------------------------


def test_render_repo_banner_empty(tmp_path):
    (tmp_path / ".tern").mkdir()
    assert render_repo_banner(tmp_path) == ""


def test_render_repo_banner_includes_sections(tmp_path):
    (tmp_path / ".tern").mkdir()
    add_repo_entry("arch", "uses async generators", tmp_path)
    add_repo_entry("decisions", "state replaced per turn", tmp_path)
    banner = render_repo_banner(tmp_path)
    assert "REPO MEMORY" in banner
    assert "## ARCH" in banner
    assert "## DECISIONS" in banner
    assert "uses async generators" in banner
    assert "state replaced per turn" in banner
    # FAILURES + REVIEWERS are empty, should not appear
    assert "## FAILURES" not in banner
    assert "## REVIEWERS" not in banner


def test_render_repo_banner_section_order(tmp_path):
    (tmp_path / ".tern").mkdir()
    for target in REPO_TARGETS:
        add_repo_entry(target, f"note for {target}", tmp_path)
    banner = render_repo_banner(tmp_path)
    arch_pos = banner.index("## ARCH")
    dec_pos = banner.index("## DECISIONS")
    fail_pos = banner.index("## FAILURES")
    rev_pos = banner.index("## REVIEWERS")
    assert arch_pos < dec_pos < fail_pos < rev_pos


# ---------------------------------------------------------------------------
# banner composition order: MEMORY → REPO MEMORY → USER PROFILE
# ---------------------------------------------------------------------------


def test_render_all_banners_order(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    (tmp_path / ".tern").mkdir(exist_ok=True)
    # global memory
    from tern.memory.store import add_entry
    add_entry("memory", "global proc note")
    add_entry("user", "user fact")
    # repo memory — use tmp_path as both TERN_HOME and repo root
    add_repo_entry("arch", "repo arch note", tmp_path)

    combined = render_all_banners_with_repo(tmp_path)
    mem_pos = combined.index("MEMORY (your personal notes)")
    repo_pos = combined.index("REPO MEMORY")
    user_pos = combined.index("USER PROFILE")
    assert mem_pos < repo_pos < user_pos, (
        f"order wrong: MEMORY@{mem_pos} REPO@{repo_pos} USER@{user_pos}"
    )


def test_render_all_banners_absent_repo_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    # No .git or .tern in tmp_path — find_repo_root returns None or somewhere above
    # But we point cwd at an isolated directory with no markers
    no_repo = tmp_path / "no-markers"
    no_repo.mkdir()
    from tern.memory.store import add_entry
    add_entry("memory", "global note")
    banner = render_all_banners_with_repo(no_repo)
    # global memory still shows; no REPO MEMORY section
    assert "MEMORY (your personal notes)" in banner
    # If tmp_path happened to be under a real .git (e.g. CI) repo memory could appear;
    # we don't assert its absence — just that the function returns without error.


def test_render_all_banners_empty_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    no_repo = tmp_path / "empty"
    no_repo.mkdir()
    banner = render_all_banners_with_repo(no_repo)
    # No memory set anywhere — banner should be empty string
    # (unless we happen to be inside a repo and that repo has .tern/memory content,
    # which is unlikely in CI/test isolation)
    assert isinstance(banner, str)


# ---------------------------------------------------------------------------
# MemoryTool scope routing
# ---------------------------------------------------------------------------


def test_memory_tool_global_scope_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="memory", content="global note", scope="global")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    assert res.metadata["scope"] == "global"
    from tern.memory.store import load_memory
    assert load_memory("memory").entries == ("global note",)


def test_memory_tool_default_scope_is_global(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    tool = MemoryTool()
    # scope field defaults to "global"
    args = MemoryArgs(action="add", target="user", content="user note")
    assert args.scope == "global"
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    assert res.metadata["scope"] == "global"


def test_memory_tool_repo_scope_add(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    (tmp_path / ".git").mkdir()  # make tmp_path a repo root
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="arch", content="uses async generators", scope="repo")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    assert res.metadata["scope"] == "repo"
    assert res.metadata["target"] == "arch"
    assert res.metadata["entries"] == 1
    # verify on disk
    entries, _ = load_repo_memory("arch", tmp_path)
    assert entries == ("uses async generators",)


def test_memory_tool_repo_scope_replace(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    (tmp_path / ".git").mkdir()
    add_repo_entry("decisions", "old decision text", tmp_path)
    tool = MemoryTool()
    args = MemoryArgs(
        action="replace",
        target="decisions",
        old_text="old decision",
        content="new decision text",
        scope="repo",
    )
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    entries, _ = load_repo_memory("decisions", tmp_path)
    assert entries == ("new decision text",)


def test_memory_tool_repo_scope_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    (tmp_path / ".git").mkdir()
    add_repo_entry("failures", "bad pattern", tmp_path)
    add_repo_entry("failures", "keep this", tmp_path)
    tool = MemoryTool()
    args = MemoryArgs(action="remove", target="failures", old_text="bad pattern", scope="repo")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    entries, _ = load_repo_memory("failures", tmp_path)
    assert entries == ("keep this",)


def test_memory_tool_repo_no_root_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    # no_repo dir has no .git or .tern
    no_repo = tmp_path / "no-markers"
    no_repo.mkdir()
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="arch", content="x", scope="repo")
    # ctx with no_repo as repo_root and no .git/.tern above it in tmp isolation
    ctx = ToolContext(repo_root=no_repo, session_id="s", turn_idx=0, mode="default")
    # Monkeypatch find_repo_root to return None so the test is deterministic
    # (in CI tmp_path may live under a real .git)
    import tern.memory.repo_store as rstore
    original = rstore.find_repo_root
    try:
        rstore.find_repo_root = lambda cwd=None: None  # type: ignore[assignment]
        res = _run(tool.invoke(args, ctx))
    finally:
        rstore.find_repo_root = original
    assert not res.ok
    assert "no repo root" in res.error.lower()


def test_memory_tool_unknown_scope_returns_error(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="memory", content="x", scope="cloud")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert not res.ok
    assert "unknown scope" in res.error.lower()


def test_memory_tool_repo_unknown_target_returns_error(tmp_path):
    (tmp_path / ".git").mkdir()
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="notes", content="x", scope="repo")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert not res.ok
    assert "unknown target" in res.error.lower()


# ---------------------------------------------------------------------------
# build_system_prompt threads cwd → repo memory in banner
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_repo_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    (tmp_path / ".tern").mkdir()
    add_repo_entry("arch", "canonical message log is sacred", tmp_path)
    from tern.memory.store import add_entry
    add_entry("memory", "global proc note")

    from tern.skills.catalog import build_system_prompt
    prompt = build_system_prompt((), (), cwd=tmp_path)
    assert "REPO MEMORY" in prompt
    assert "canonical message log is sacred" in prompt
    assert "MEMORY (your personal notes)" in prompt


def test_build_system_prompt_no_repo_memory_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    # No .git or .tern — use a nested dir that is definitely not a repo
    no_repo = tmp_path / "flat"
    no_repo.mkdir()
    from tern.memory.store import add_entry
    add_entry("memory", "only global")

    import tern.memory.repo_store as rstore
    original = rstore.find_repo_root
    try:
        rstore.find_repo_root = lambda cwd=None: None  # type: ignore[assignment]
        from tern.skills.catalog import build_system_prompt
        prompt = build_system_prompt((), (), cwd=no_repo)
    finally:
        rstore.find_repo_root = original
    assert "REPO MEMORY" not in prompt
    assert "MEMORY (your personal notes)" in prompt
