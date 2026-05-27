"""Registry: registration, name lookup, mode-aware visibility."""

from __future__ import annotations

import pytest

from tern.tools import Registry
from tests.tools._fakes import FakeDestructiveTool, FakeReadOnlyTool


def test_register_and_lookup() -> None:
    r = Registry([FakeReadOnlyTool()])
    assert "fake_read" in r
    assert r.get("fake_read") is not None
    assert r.get("missing") is None
    assert len(r) == 1


def test_duplicate_register_rejected() -> None:
    r = Registry([FakeReadOnlyTool()])
    with pytest.raises(ValueError, match="duplicate tool name"):
        r.register(FakeReadOnlyTool())


def test_safe_mode_drops_destructive_at_registry() -> None:
    r = Registry([FakeReadOnlyTool(), FakeDestructiveTool()])
    safe = [t.name for t in r.visible_to_model(mode="safe")]
    assert safe == ["fake_read"]
    default = [t.name for t in r.visible_to_model(mode="default")]
    assert default == ["fake_read", "fake_write"]
    yolo = [t.name for t in r.visible_to_model(mode="yolo")]
    assert yolo == ["fake_read", "fake_write"]


def test_specs_renders_to_canonical_toolspec() -> None:
    r = Registry([FakeReadOnlyTool(), FakeDestructiveTool()])
    specs = r.specs(mode="safe")
    assert len(specs) == 1
    assert specs[0].name == "fake_read"
