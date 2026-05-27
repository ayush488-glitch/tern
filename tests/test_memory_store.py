"""S15 — memory store: load/save MEMORY.md & USER.md, banner rendering."""

from __future__ import annotations

import pytest

from tern.memory.store import (
    MEMORY_CAP,
    USER_CAP,
    add_entry,
    load_memory,
    memory_path,
    remove_entry,
    render_all_banners,
    render_banner,
    replace_entry,
    user_path,
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    yield


def test_empty_memory_loads_clean():
    snap = load_memory("memory")
    assert snap.entries == ()
    assert snap.text == ""
    assert snap.cap == MEMORY_CAP
    assert not snap.over_cap
    assert render_banner(snap) == ""


def test_add_entry_round_trips():
    snap = add_entry("memory", "first note")
    assert snap.entries == ("first note",)
    on_disk = memory_path().read_text("utf-8")
    assert "first note" in on_disk
    # second entry adds the § separator, not duplicates
    snap2 = add_entry("memory", "second note")
    assert snap2.entries == ("first note", "second note")
    assert on_disk.count("§") == 0  # only first add — re-read for second
    after = memory_path().read_text("utf-8")
    assert after.count("§") == 1


def test_user_target_writes_to_user_md():
    add_entry("user", "calls me Iyela")
    assert user_path().exists()
    assert "Iyela" in user_path().read_text("utf-8")
    # memory.md must NOT contain it
    assert not memory_path().exists() or "Iyela" not in memory_path().read_text(
        "utf-8"
    )


def test_replace_by_substring():
    add_entry("memory", "AWS region us-east-1 only")
    add_entry("memory", "Bedrock claude-4 needs us. prefix")
    replace_entry("memory", "us-east-1", "AWS region us-west-2 only")
    snap = load_memory("memory")
    assert any("us-west-2" in e for e in snap.entries)
    assert all("us-east-1" not in e for e in snap.entries)


def test_replace_ambiguous_match_raises():
    add_entry("memory", "shared keyword apple")
    add_entry("memory", "shared keyword banana")
    with pytest.raises(LookupError, match="matches 2"):
        replace_entry("memory", "shared keyword", "merged")


def test_replace_no_match_raises():
    add_entry("memory", "only entry")
    with pytest.raises(LookupError, match="no memory entry"):
        replace_entry("memory", "ghost", "x")


def test_remove_drops_one_entry():
    add_entry("memory", "keep me")
    add_entry("memory", "delete me")
    remove_entry("memory", "delete me")
    snap = load_memory("memory")
    assert snap.entries == ("keep me",)


def test_empty_content_rejected():
    with pytest.raises(ValueError):
        add_entry("memory", "   ")


def test_unknown_target_rejected():
    from tern.memory.store import load_memory as lm
    with pytest.raises(ValueError):
        lm("garbage")  # type: ignore[arg-type]


def test_atomic_write_no_temp_file_left_behind():
    add_entry("memory", "first")
    add_entry("memory", "second")
    leftovers = list((memory_path().parent).glob(".memory-*"))
    assert leftovers == []


def test_banner_includes_pct_and_title():
    add_entry("memory", "x" * 500)
    snap = load_memory("memory")
    rendered = render_banner(snap)
    assert "MEMORY (your personal notes)" in rendered
    assert "/" + str(MEMORY_CAP) in rendered
    assert "%" in rendered


def test_banner_flags_over_cap():
    add_entry("user", "x" * (USER_CAP + 200))
    snap = load_memory("user")
    assert snap.over_cap
    assert "OVER CAP" in render_banner(snap)


def test_render_all_banners_composes_both():
    add_entry("memory", "proc note")
    add_entry("user", "user fact")
    blob = render_all_banners()
    assert "MEMORY" in blob and "USER PROFILE" in blob
    # MEMORY block precedes USER block
    assert blob.index("MEMORY") < blob.index("USER PROFILE")


def test_render_all_banners_empty_when_no_files():
    assert render_all_banners() == ""


def test_separator_round_trips_multi_paragraph():
    multi = "line A\nline B\nline C"
    add_entry("memory", multi)
    snap = load_memory("memory")
    assert snap.entries == (multi,)


def test_unicode_entries_round_trip():
    add_entry("memory", "用户偏好: 简洁回复 ✓")
    snap = load_memory("memory")
    assert snap.entries[0] == "用户偏好: 简洁回复 ✓"


def test_entries_equal_separator_line_are_handled():
    # if a user pasted "§" alone they'd break the format — `add_entry` strips
    # it down to '§' which is whitespace-meaningful but not blank, so it survives
    snap = add_entry("memory", "before § after")
    assert snap.entries == ("before § after",)
