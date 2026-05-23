"""Minimal MCP stdio client for the Claude-Code-style agent harness.

Spawns an upstream MCP server, performs the initialize handshake, and exposes
list_tools() + call_tool() so the agent loop can route Claude's tool_use
blocks back to the right server.

Built on the official `mcp` Python SDK's stdio_client + ClientSession.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class McpServerSpec:
    """How to launch one MCP server."""
    name: str                       # logical name (e.g. "polycodegraph")
    command: str                    # binary to exec
    args: list[str]                 # CLI args
    cwd: Path | None = None
    env: dict[str, str] | None = None


@dataclass
class McpTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def qualified_name(self) -> str:
        """Tool names exposed to Claude — namespaced so two servers can both ship `find_symbol`."""
        return f"{self.server}__{self.name}"


class McpSession:
    """One connected MCP server + cached tool list."""

    def __init__(self, spec: McpServerSpec) -> None:
        self.spec = spec
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: list[McpTool] = []

    async def __aenter__(self) -> McpSession:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        params = StdioServerParameters(
            command=self.spec.command,
            args=self.spec.args,
            cwd=str(self.spec.cwd) if self.spec.cwd else None,
            env=self.spec.env,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listed = await self._session.list_tools()
        self._tools = [
            McpTool(
                server=self.spec.name,
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {"type": "object", "properties": {}},
            )
            for t in listed.tools
        ]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, tb)
            self._stack = None
            self._session = None

    @property
    def tools(self) -> list[McpTool]:
        return self._tools

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            raise RuntimeError("McpSession used outside `async with`")
        result = await self._session.call_tool(tool_name, arguments)
        # Collapse content blocks into one text payload for the agent loop.
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)


def to_anthropic_tools(sessions: list[McpSession]) -> list[dict[str, Any]]:
    """Flatten every session's tools into Anthropic tool definitions."""
    out: list[dict[str, Any]] = []
    for s in sessions:
        for t in s.tools:
            out.append({
                "name": t.qualified_name(),
                "description": t.description[:1024],  # Anthropic caps description length
                "input_schema": t.input_schema,
            })
    return out


def find_session(sessions: list[McpSession], qualified_name: str) -> tuple[McpSession, str] | None:
    """Reverse the namespacing: `polycodegraph__find_symbol` -> (session, "find_symbol")."""
    if "__" not in qualified_name:
        return None
    server, tool_name = qualified_name.split("__", 1)
    for s in sessions:
        if s.spec.name == server:
            return s, tool_name
    return None


def run_async(coro):
    """Convenience: run an async function from sync code."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Multi-session orchestration
# ---------------------------------------------------------------------------
#
# Using AsyncExitStack to manage N McpSessions causes anyio cancel-scope
# crashes ("entered in different task than exited") because each session opens
# its own internal task group via stdio_client. AsyncExitStack closes them in
# reverse order from a different task than each was entered in.
#
# Fix: recurse with nested `async with` blocks so every session's enter/exit
# happens in the same lexical scope and the same task. Slightly uglier, much
# more robust.


async def with_sessions(
    specs: list[McpServerSpec],
    body: Callable[[list[LiveSession]], Awaitable[Any]],
) -> Any:
    """Open all `specs` as MCP sessions, then call `body` with a flat list of
    live sessions. Closes everything in reverse order when `body` returns or raises.
    """
    return await _open_recursive(specs, [], body)


@dataclass
class LiveSession:
    """An already-initialized MCP session with cached tool list."""
    spec: McpServerSpec
    session: ClientSession
    tools: list[McpTool]

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = await self.session.call_tool(tool_name, arguments)
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)


async def _open_recursive(
    remaining: list[McpServerSpec],
    opened: list[LiveSession],
    body: Callable[[list[LiveSession]], Awaitable[Any]],
) -> Any:
    if not remaining:
        return await body(opened)
    spec, *rest = remaining
    params = StdioServerParameters(
        command=spec.command,
        args=spec.args,
        cwd=str(spec.cwd) if spec.cwd else None,
        env=spec.env,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        tools = [
            McpTool(
                server=spec.name,
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {"type": "object", "properties": {}},
            )
            for t in listed.tools
        ]
        live = LiveSession(spec=spec, session=session, tools=tools)
        return await _open_recursive(rest, [*opened, live], body)


def live_to_anthropic_tools(sessions: list[LiveSession]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in sessions:
        for t in s.tools:
            out.append({
                "name": t.qualified_name(),
                "description": t.description[:1024],
                "input_schema": t.input_schema,
            })
    return out


def find_live_session(
    sessions: list[LiveSession], qualified_name: str,
) -> tuple[LiveSession, str] | None:
    if "__" not in qualified_name:
        return None
    server, tool_name = qualified_name.split("__", 1)
    for s in sessions:
        if s.spec.name == server:
            return s, tool_name
    return None
