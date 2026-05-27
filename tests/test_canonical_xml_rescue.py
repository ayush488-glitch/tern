"""S15 — pseudo-XML tool-call rescue parser."""

from __future__ import annotations

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
    ToolCallBlock,
    lift_pseudo_xml_tool_calls,
)


def _msg(text: str) -> CanonicalMessage:
    return CanonicalMessage(
        role="assistant",
        content=(TextBlock(text=text),),
        metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="test"),
    )


def test_no_xml_returns_msg_unchanged():
    msg = _msg("just a normal reply, no tags")
    out = lift_pseudo_xml_tool_calls(msg, frozenset({"notes_append"}))
    assert out is msg or out == msg


def test_xml_for_unknown_tool_left_alone():
    msg = _msg("<random>not a tool</random>")
    out = lift_pseudo_xml_tool_calls(msg, frozenset({"notes_append"}))
    # text untouched, no ToolCallBlock added
    assert all(isinstance(b, TextBlock) for b in out.content)


def test_lifts_known_tool_into_tool_call():
    msg = _msg("<notes_append>finished S15</notes_append>")
    out = lift_pseudo_xml_tool_calls(msg, frozenset({"notes_append"}))
    calls = [b for b in out.content if isinstance(b, ToolCallBlock)]
    assert len(calls) == 1
    assert calls[0].name == "notes_append"
    assert calls[0].args == {"text": "finished S15"}
    assert calls[0].id.startswith("rescue_")


def test_preserves_surrounding_prose():
    msg = _msg("ok done. <notes_append>milestone hit</notes_append> next up: ship.")
    out = lift_pseudo_xml_tool_calls(msg, frozenset({"notes_append"}))
    texts = [b.text for b in out.content if isinstance(b, TextBlock)]
    calls = [b for b in out.content if isinstance(b, ToolCallBlock)]
    assert "ok done." in texts
    assert "next up: ship." in texts
    assert len(calls) == 1


def test_multiple_calls_lifted():
    msg = _msg(
        "<notes_append>first</notes_append> mid "
        "<notes_append>second</notes_append>"
    )
    out = lift_pseudo_xml_tool_calls(msg, frozenset({"notes_append"}))
    calls = [b for b in out.content if isinstance(b, ToolCallBlock)]
    assert [c.args["text"] for c in calls] == ["first", "second"]


def test_empty_allowed_set_is_noop():
    msg = _msg("<notes_append>x</notes_append>")
    out = lift_pseudo_xml_tool_calls(msg, frozenset())
    assert out == msg


def test_idempotent():
    msg = _msg("<notes_append>only one</notes_append>")
    once = lift_pseudo_xml_tool_calls(msg, frozenset({"notes_append"}))
    twice = lift_pseudo_xml_tool_calls(once, frozenset({"notes_append"}))
    # second pass finds no TextBlock with the pattern; result equal
    once_calls = [b for b in once.content if isinstance(b, ToolCallBlock)]
    twice_calls = [b for b in twice.content if isinstance(b, ToolCallBlock)]
    assert len(once_calls) == len(twice_calls) == 1
