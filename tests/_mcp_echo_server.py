"""Minimal stdio MCP server used by integration tests.

Exposes one tool: ``echo`` — returns the argument back as text. Stays in this
file so integration tests can spawn it as ``python <path>`` with no install.
"""

from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


def build() -> Server:
    server: Server = Server("tern-test-echo")

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [
            Tool(
                name="echo",
                description="Echo a message back as text.",
                inputSchema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            )
        ]

    @server.call_tool()
    async def _call(name: str, args: dict) -> list[TextContent]:
        if name != "echo":
            raise ValueError(f"unknown tool {name}")
        return [TextContent(type="text", text=f"echo: {args.get('message', '')}")]

    return server


async def _main() -> None:
    server = build()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
