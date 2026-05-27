"""S12 / D4 — tests for notes store, render, and the notes_append tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Cost,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from tern.notes import append_note, notes_path, read_notes, render_html
from tern.notes.store import truncate_notes
from tern.obs.store import persist_message, update_session_head
from tern.tools.native.notes_append import NotesAppendArgs, NotesAppendTool
from tern.tools.protocol import ToolContext

# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


def test_append_and_read_notes_roundtrip(tmp_path: Path) -> None:
    sid = "sess001"
    n = append_note(sid, "first finding", turn_idx=0, cwd=tmp_path, ts=1.0)
    assert n.text == "first finding"
    append_note(sid, "second", turn_idx=1, tags=("decision",), cwd=tmp_path, ts=2.0)
    rows = read_notes(sid, cwd=tmp_path)
    assert len(rows) == 2
    assert rows[0].text == "first finding"
    assert rows[1].tags == ("decision",)
    assert rows[1].turn_idx == 1


def test_read_notes_missing_returns_empty(tmp_path: Path) -> None:
    assert read_notes("nope", cwd=tmp_path) == ()


def test_read_notes_tolerates_partial_trailing_line(tmp_path: Path) -> None:
    sid = "sess-bad"
    append_note(sid, "good row", turn_idx=0, cwd=tmp_path, ts=1.0)
    p = notes_path(sid, cwd=tmp_path)
    with p.open("a", encoding="utf-8") as f:
        f.write("{not-json")  # crash-mid-write
    rows = read_notes(sid, cwd=tmp_path)
    assert len(rows) == 1
    assert rows[0].text == "good row"


def test_truncate_notes(tmp_path: Path) -> None:
    sid = "sess-trunc"
    append_note(sid, "row", turn_idx=0, cwd=tmp_path)
    truncate_notes(sid, cwd=tmp_path)
    assert read_notes(sid, cwd=tmp_path) == ()


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _seed_session(tmp_path: Path, sid: str) -> None:
    """Persist a tiny user→assistant chain so render_html has something to walk."""
    user = CanonicalMessage(
        role="user",
        content=(TextBlock(text="hello world"),),
        metadata=__import__("tern.core.canonical", fromlist=["Metadata"]).Metadata(
            schema_version=SCHEMA_VERSION, ts=0.0
        ),
    )
    _, parent = persist_message(
        user, session_id=sid, turn_idx=0, parent=None, cwd=tmp_path
    )
    update_session_head(sid, parent, cwd=tmp_path)

    asst = CanonicalMessage(
        role="assistant",
        content=(
            TextBlock(text="hi back"),
            ToolCallBlock(id="c1", name="read_file", args={"path": "x.txt"}),
            ToolResultBlock(call_id="c1", ok=True, content="x.txt|hi"),
        ),
        metadata=__import__("tern.core.canonical", fromlist=["Metadata"]).Metadata(
            schema_version=SCHEMA_VERSION,
            ts=1.0,
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
            cost=Cost(input_tokens=10, output_tokens=5, usd_in=0.0001, usd_out=0.0002),
        ),
    )
    _, head = persist_message(
        asst, session_id=sid, turn_idx=0, parent=parent, cwd=tmp_path
    )
    update_session_head(sid, head, cwd=tmp_path)


def test_render_html_writes_file_with_expected_sections(tmp_path: Path) -> None:
    sid = "sess-render"
    _seed_session(tmp_path, sid)
    append_note(sid, "decision: skip caching", turn_idx=0, cwd=tmp_path, ts=2.0)

    out = render_html(sid, cwd=tmp_path)
    assert out.exists()
    body = out.read_text("utf-8")
    assert "<!doctype html>" in body
    assert sid in body
    assert "summary" in body
    assert "transcript" in body
    assert "decision: skip caching" in body
    assert "hello world" in body
    assert "hi back" in body
    # tool blocks
    assert "read_file" in body
    assert "x.txt|hi" in body
    # cost summary
    assert "$0.0003" in body


def test_render_html_html_escapes_user_content(tmp_path: Path) -> None:
    sid = "sess-xss"
    _seed_session(tmp_path, sid)
    append_note(sid, "<script>alert(1)</script>", turn_idx=0, cwd=tmp_path)
    body = render_html(sid, cwd=tmp_path).read_text("utf-8")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_render_html_handles_session_with_no_turns(tmp_path: Path) -> None:
    out = render_html("ghost-session", cwd=tmp_path)
    body = out.read_text("utf-8")
    assert "no turns recorded yet" in body
    assert "no notes appended" in body


def test_render_html_respects_out_path(tmp_path: Path) -> None:
    sid = "sess-out"
    _seed_session(tmp_path, sid)
    target = tmp_path / "docs" / "notes.html"
    out = render_html(sid, cwd=tmp_path, out_path=target)
    assert out == target
    assert target.exists()


# ---------------------------------------------------------------------------
# tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_append_tool_writes_row_with_context(tmp_path: Path) -> None:
    tool = NotesAppendTool()
    ctx = ToolContext(
        repo_root=tmp_path, session_id="sess-tool", turn_idx=3, mode="default"
    )
    args = NotesAppendArgs(text=" hello there  ", tags=["decision", "d4"])
    result = await tool.invoke(args, ctx)
    assert result.ok
    rows = read_notes("sess-tool", cwd=tmp_path)
    assert len(rows) == 1
    assert rows[0].text == "hello there"
    assert rows[0].turn_idx == 3
    assert rows[0].tags == ("decision", "d4")
    assert "noted" in result.content


def test_notes_append_tool_annotations_are_non_destructive() -> None:
    tool = NotesAppendTool()
    assert not tool.annotations.destructive


def test_notes_append_args_reject_empty_text() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NotesAppendArgs(text="")


def test_notes_append_tool_appears_in_native_exports() -> None:
    from tern.tools.native import NotesAppendTool as _Imported

    assert _Imported is NotesAppendTool


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)
