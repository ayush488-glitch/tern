"""Tests for the MCP bridge (D6 / S13).

We don't spawn a real MCP server. Tests cover:
  - config loader (project shadows user, missing files = empty, malformed = skipped)
  - _bridge_result mapping
  - _make_bridge produces a Tool-shaped object with correct annotations
  - MCPBridgedTool.invoke maps payload through, handles failure
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from tern.tools.mcp import (
    MCPBridgedTool,
    _bridge_result,
    _make_bridge,
    load_mcp_config,
)
from tern.tools.protocol import Tool, ToolAnnotations, ToolContext

# ---------------------------------------------------------------------------
# config loader
# ---------------------------------------------------------------------------


def test_load_mcp_config_missing_files(tmp_path: Path) -> None:
    """No config files anywhere → empty tuple, no exception."""
    assert load_mcp_config(tmp_path) == ()


def test_load_mcp_config_project_only(tmp_path: Path) -> None:
    cfg = tmp_path / ".tern" / "mcp.json"
    cfg.parent.mkdir()
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}
                }
            }
        )
    )
    out = load_mcp_config(tmp_path)
    assert len(out) == 1
    assert out[0].name == "fetch"
    assert out[0].command == "uvx"
    assert out[0].args == ("mcp-server-fetch",)


def test_load_mcp_config_malformed_skipped(tmp_path: Path) -> None:
    cfg = tmp_path / ".tern" / "mcp.json"
    cfg.parent.mkdir()
    cfg.write_text("{not json")
    assert load_mcp_config(tmp_path) == ()


def test_load_mcp_config_drops_no_command(tmp_path: Path) -> None:
    cfg = tmp_path / ".tern" / "mcp.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"mcpServers": {"bad": {"args": ["x"]}}}))
    assert load_mcp_config(tmp_path) == ()


# ---------------------------------------------------------------------------
# bridge result
# ---------------------------------------------------------------------------


def test_bridge_result_text_only() -> None:
    parts = [SimpleNamespace(type="text", text="hello"), SimpleNamespace(type="text", text="world")]
    result = SimpleNamespace(content=parts, isError=False)
    out = _bridge_result("srv", "tool", result)
    assert out.ok
    assert "hello" in out.content and "world" in out.content
    assert out.metadata["server"] == "srv"


def test_bridge_result_error_flag() -> None:
    parts = [SimpleNamespace(type="text", text="boom")]
    result = SimpleNamespace(content=parts, isError=True)
    out = _bridge_result("srv", "tool", result)
    assert not out.ok
    assert "boom" in out.content


def test_bridge_result_artifact_count() -> None:
    parts = [
        SimpleNamespace(type="text", text="ok"),
        SimpleNamespace(type="image", data="..."),
        SimpleNamespace(type="image", data="..."),
    ]
    result = SimpleNamespace(content=parts, isError=False)
    out = _bridge_result("srv", "tool", result)
    assert out.metadata["artifacts"] == 2


# ---------------------------------------------------------------------------
# make_bridge
# ---------------------------------------------------------------------------


def test_make_bridge_maps_annotations() -> None:
    """Annotations from MCP (camelCase hints) → ToolAnnotations (snake)."""
    raw_anno = SimpleNamespace(
        destructiveHint=True,
        idempotentHint=False,
        readOnlyHint=False,
        openWorldHint=True,
    )
    t = SimpleNamespace(
        name="fetch",
        title="Fetch URL",
        description="fetch a URL",
        inputSchema={"type": "object", "properties": {"url": {"type": "string"}}},
        annotations=raw_anno,
    )

    class FakeSession:
        async def call_tool(self, name: str, payload: dict) -> object:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="OK")], isError=False
            )

    bridge = _make_bridge(FakeSession(), "fetch-srv", t)
    assert isinstance(bridge, MCPBridgedTool)
    assert bridge.name == "fetch"
    assert bridge.annotations.destructive is True
    assert bridge.annotations.idempotent is False
    assert bridge.annotations.open_world is True
    # Tool Protocol structural conformance
    assert isinstance(bridge, Tool)


def test_make_bridge_default_annotations() -> None:
    """No annotations on remote tool → defaults (idempotent True, others False)."""
    t = SimpleNamespace(
        name="x", title=None, description="", inputSchema=None, annotations=None
    )
    bridge = _make_bridge(SimpleNamespace(), "srv", t)
    assert bridge.annotations == ToolAnnotations(
        destructive=False, idempotent=True, read_only=False, open_world=False
    )
    assert bridge.input_schema == {"type": "object"}


# ---------------------------------------------------------------------------
# invoke
# ---------------------------------------------------------------------------


def test_bridged_invoke_success(tmp_path: Path) -> None:
    captured: dict = {}

    async def call(name: str, payload: dict):  # type: ignore[no-untyped-def]
        captured["name"] = name
        captured["payload"] = payload
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hi")], isError=False
        )

    bridge = MCPBridgedTool(
        name="echo",
        title="echo",
        description="",
        input_schema={"type": "object"},
        annotations=ToolAnnotations(),
        server_name="srv",
        _call=call,
    )
    args = bridge.args_model.model_validate({"foo": "bar"})
    ctx = ToolContext(repo_root=tmp_path, session_id="s", turn_idx=0, mode="default")
    res = asyncio.run(bridge.invoke(args, ctx))
    assert res.ok
    assert "hi" in res.content
    assert captured == {"name": "echo", "payload": {"foo": "bar"}}


def test_bridged_invoke_failure_returned_not_raised(tmp_path: Path) -> None:
    async def call(name: str, payload: dict):  # type: ignore[no-untyped-def]
        raise RuntimeError("server crashed")

    bridge = MCPBridgedTool(
        name="x",
        title="x",
        description="",
        input_schema={"type": "object"},
        annotations=ToolAnnotations(),
        server_name="srv",
        _call=call,
    )
    args = bridge.args_model.model_validate({})
    ctx = ToolContext(repo_root=tmp_path, session_id="s", turn_idx=0, mode="default")
    res = asyncio.run(bridge.invoke(args, ctx))
    assert not res.ok
    assert "server crashed" in (res.error or "")
