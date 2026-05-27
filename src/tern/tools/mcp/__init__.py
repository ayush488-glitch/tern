"""MCP client bridge — D6 / S13.

Connects to one or more MCP servers (stdio for v0; HTTP later) and bridges
each remote tool into a local ``Tool`` so the registry, the gate, and the
adapter all see one uniform surface.

Why bridge at the Tool Protocol layer (not at the adapter): the gate needs
the same ToolAnnotations to decide approval, the spans recorder needs the
same ToolContext stamp, and replay needs deterministic args validation.
Bridging higher up means MCP tools earn all that for free.

Lifecycle: ``MCPManager`` is opened once at chat/run start, kept alive for
the duration of the process, and closed in a finally block. Each connected
server is one ``ClientSession`` inside an ``AsyncExitStack`` so ``aclose()``
unwinds cleanly even if one server died.

Pitfalls captured:
- Args model is built dynamically with a single dict[str, Any] payload
  validated against the server's JSON Schema at call-time. We do NOT try to
  generate a Pydantic class per remote tool; that gets messy fast and the
  gate doesn't need it. Adapters serialize the JSON Schema directly.
- MCP returns a list of content parts (text, image). We concatenate text
  parts and stash images in metadata['artifacts'] for now (S13 doesn't ship
  the vision side; that's S14).
- A failing call returns ``ToolResult(ok=False, ...)`` instead of raising —
  the loop already knows how to feed that back to the model.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from tern.tools.protocol import Tool, ToolAnnotations, ToolContext, ToolResult

# ---------------------------------------------------------------------------
# args model — one shared shape for every remote tool
# ---------------------------------------------------------------------------


class _PassthroughArgs(BaseModel):
    """Accepts any dict. We delegate validation to the server's schema."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MCPServerConfig:
    """One stdio server. Shape mirrors Claude Code / Cursor mcp.json."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


def load_mcp_config(cwd: Path | None = None) -> tuple[MCPServerConfig, ...]:
    """Resolve `.tern/mcp.json` (project) merged over `~/.tern/mcp.json` (user).

    Project entries shadow user entries on name collision (same precedence as
    skills, ADR-0006). Missing files = empty config; never raises.
    """
    base = (cwd or Path.cwd()).resolve()
    project = base / ".tern" / "mcp.json"
    user = Path.home() / ".tern" / "mcp.json"
    merged: dict[str, MCPServerConfig] = {}
    for path in (user, project):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        for name, entry in (data.get("mcpServers") or {}).items():
            if not isinstance(entry, dict):
                continue
            merged[name] = MCPServerConfig(
                name=name,
                command=str(entry.get("command", "")),
                args=tuple(str(a) for a in (entry.get("args") or [])),
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
            )
    return tuple(s for s in merged.values() if s.command)


# ---------------------------------------------------------------------------
# bridged tool
# ---------------------------------------------------------------------------


@dataclass
class MCPBridgedTool:
    """A local Tool backed by one remote MCP tool.

    Built by ``MCPManager`` once we've called ``list_tools`` on the server.
    """

    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    annotations: ToolAnnotations
    server_name: str
    _call: Any  # callable returning awaitable -> CallToolResult
    args_model: type[BaseModel] = _PassthroughArgs

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        try:
            payload = args.model_dump(exclude_none=True)
        except Exception:
            payload = {}
        try:
            result = await self._call(self.name, payload)
        except Exception as exc:
            return ToolResult(
                ok=False,
                content=f"mcp call failed ({self.server_name}/{self.name}): {exc}",
                error=str(exc),
            )
        return _bridge_result(self.server_name, self.name, result)


def _bridge_result(server: str, tool: str, result: Any) -> ToolResult:
    """Map an MCP CallToolResult onto our ToolResult.

    Defensive: the MCP SDK shape evolves; we only touch ``content`` (a list
    of parts with ``type``/``text``) and ``isError``.
    """
    is_error = bool(getattr(result, "isError", False))
    parts = getattr(result, "content", None) or []
    text_chunks: list[str] = []
    artifact_count = 0
    for p in parts:
        ptype = getattr(p, "type", None)
        if ptype == "text":
            text_chunks.append(getattr(p, "text", "") or "")
        else:
            artifact_count += 1
    body = "\n".join(text_chunks).strip() or f"(no text content from {server}/{tool})"
    meta: dict[str, Any] = {"server": server, "tool": tool}
    if artifact_count:
        meta["artifacts"] = artifact_count
    return ToolResult(ok=not is_error, content=body, metadata=meta)


# ---------------------------------------------------------------------------
# manager
# ---------------------------------------------------------------------------


class MCPManager:
    """Owns connections to N stdio MCP servers; exposes bridged Tools.

    Usage::

        async with MCPManager.connect(load_mcp_config()) as mgr:
            registry.extend(mgr.tools)
            ...

    Or, if you can't use ``async with``::

        mgr = MCPManager()
        await mgr.start(servers)
        try:
            ...
        finally:
            await mgr.aclose()
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._sessions: dict[str, Any] = {}
        self._tools: list[MCPBridgedTool] = []

    @property
    def tools(self) -> list[MCPBridgedTool]:
        return list(self._tools)

    @classmethod
    def connect(cls, servers: tuple[MCPServerConfig, ...]) -> _MCPCtx:
        return _MCPCtx(cls(), servers)

    async def start(self, servers: tuple[MCPServerConfig, ...]) -> None:
        """Spin up each server; populate ``self._tools``. Continues on per-server failure."""
        # Lazy import — keep the rest of the package importable without the dep.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        for srv in servers:
            try:
                params = StdioServerParameters(
                    command=srv.command, args=list(srv.args), env=srv.env or None
                )
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(
                    ClientSession(read, write)
                )
                await asyncio.wait_for(session.initialize(), timeout=15.0)
                self._sessions[srv.name] = session
                listing = await session.list_tools()
                for t in listing.tools:
                    self._tools.append(_make_bridge(session, srv.name, t))
            except Exception:
                # one bad server doesn't kill the others; log via spans later
                continue

    async def aclose(self) -> None:
        await self._stack.aclose()


@dataclass
class _MCPCtx:
    """Tiny ``async with`` wrapper around ``MCPManager.start``/``aclose``."""

    mgr: MCPManager
    servers: tuple[MCPServerConfig, ...]

    async def __aenter__(self) -> MCPManager:
        await self.mgr.start(self.servers)
        return self.mgr

    async def __aexit__(self, *exc: Any) -> None:
        await self.mgr.aclose()


def _make_bridge(session: Any, server_name: str, t: Any) -> MCPBridgedTool:
    """Build one MCPBridgedTool from an MCP ``Tool`` model."""
    raw_anno = getattr(t, "annotations", None)
    annos = ToolAnnotations(
        destructive=bool(getattr(raw_anno, "destructiveHint", False)),
        idempotent=bool(getattr(raw_anno, "idempotentHint", True)),
        read_only=bool(getattr(raw_anno, "readOnlyHint", False)),
        open_world=bool(getattr(raw_anno, "openWorldHint", False)),
    )

    async def _call(name: str, payload: dict[str, Any]) -> Any:
        return await session.call_tool(name, payload)

    return MCPBridgedTool(
        name=t.name,
        title=getattr(t, "title", None) or t.name,
        description=t.description or "",
        input_schema=t.inputSchema or {"type": "object"},
        annotations=annos,
        server_name=server_name,
        _call=_call,
    )


# Tool Protocol conformance check (mypy-static; runtime is a Protocol)
_PROTOCOL_CHECK: type[Tool] = MCPBridgedTool  # type: ignore[assignment,unused-ignore]


__all__ = [
    "MCPBridgedTool",
    "MCPManager",
    "MCPServerConfig",
    "load_mcp_config",
]
