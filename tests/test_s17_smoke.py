"""S17 live smoke — write to repo memory and recall it in the next turn's banner."""
from __future__ import annotations

import os

import pytest


@pytest.mark.skipif(os.environ.get("TERN_LIVE") != "1", reason="live smoke: set TERN_LIVE=1")
def test_s17_live_smoke_repo_memory_round_trip(tmp_path):
    """Write to repo memory then verify it appears in the system prompt banner."""
    os.environ["TERN_HOME"] = str(tmp_path)
    (tmp_path / ".git").mkdir()  # make it a detectable repo root

    from tern.memory.repo_store import add_repo_entry, load_repo_memory, render_repo_banner
    from tern.memory.store import add_entry, render_all_banners_with_repo
    from tern.skills.catalog import build_system_prompt

    # write to all four repo targets
    add_repo_entry("arch", "async generator loop, never blocking", tmp_path)
    add_repo_entry("decisions", "state replaced each turn (ADR-0002)", tmp_path)
    add_repo_entry("failures", "Kimi K2.5 tool schema 400 on Bedrock", tmp_path)
    add_repo_entry("reviewers", "Ayush reviews by checking tests first", tmp_path)

    # write global memory too
    add_entry("memory", "global: Python 3.10 on macOS")
    add_entry("user", "name: Ayush")

    # verify repo banner
    banner = render_repo_banner(tmp_path)
    assert "REPO MEMORY" in banner
    for kw in ["async generator", "ADR-0002", "Kimi K2.5", "tests first"]:
        assert kw in banner, f"missing: {kw}"

    # verify full compose order: MEMORY < REPO MEMORY < USER PROFILE
    full = render_all_banners_with_repo(tmp_path)
    mem_pos = full.index("MEMORY (your personal notes)")
    repo_pos = full.index("REPO MEMORY")
    user_pos = full.index("USER PROFILE")
    assert mem_pos < repo_pos < user_pos, "banner order wrong"

    # verify build_system_prompt threads cwd through
    sys_prompt = build_system_prompt((), (), cwd=tmp_path)
    assert "REPO MEMORY" in sys_prompt
    assert "async generator" in sys_prompt

    # recall: reload from disk (simulates next turn — repo memory persists)
    entries, _ = load_repo_memory("arch", tmp_path)
    assert entries == ("async generator loop, never blocking",)
    print("S17 live smoke: all assertions passed.")
