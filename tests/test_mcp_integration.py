"""End-to-end integration: spawn a real MCP server, bridge it, invoke the tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tern.tools.mcp import MCPManager, load_mcp_config
from tern.tools.protocol import ToolContext


def _write_cfg(tmp_path: Path) -> None:
    server_script = Path(__file__).parent / "_mcp_echo_server.py"
    cfg = tmp_path / ".tern" / "mcp.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "echo": {
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                }
            }
        )
    )


@pytest.mark.asyncio
async def test_real_mcp_server_bridge(tmp_path: Path) -> None:
    _write_cfg(tmp_path)
    servers = load_mcp_config(tmp_path)
    assert len(servers) == 1

    async with MCPManager.connect(servers) as mgr:
        names = [t.name for t in mgr.tools]
        assert "echo" in names
        echo = next(t for t in mgr.tools if t.name == "echo")
        args = echo.args_model.model_validate({"message": "hi"})
        ctx = ToolContext(
            repo_root=tmp_path, session_id="s", turn_idx=0, mode="default"
        )
        res = await echo.invoke(args, ctx)
        assert res.ok, res.error
        assert "echo: hi" in res.content
