"""Tool Protocol structural conformance + spec_for() bridge."""

from __future__ import annotations

from tern.tools import Tool, spec_for
from tests.tools._fakes import FakeDestructiveTool, FakeReadOnlyTool


def test_fakes_conform_to_tool_protocol() -> None:
    assert isinstance(FakeReadOnlyTool(), Tool)
    assert isinstance(FakeDestructiveTool(), Tool)


def test_spec_for_emits_pydantic_json_schema() -> None:
    spec = spec_for(FakeReadOnlyTool())
    assert spec.name == "fake_read"
    # extra="forbid" should land in the schema; the model can't smuggle params.
    assert spec.input_schema.get("additionalProperties") is False
    # the auto-injected pydantic title is stripped — keeps tool list compact.
    assert "title" not in spec.input_schema
    # payload is the only declared field.
    assert "payload" in spec.input_schema.get("properties", {})
