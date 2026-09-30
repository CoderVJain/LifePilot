"""The MCP server. Streamable HTTP, spec 2025-11-25 or later, official SDK called at runtime.

`streamable_http_app()` returns a Starlette app whose lifespan already enters
`session_manager.run()`. Wrapping it in a FastAPI app would break that -- a mounted sub-app's lifespan
never runs, and every request would hang -- so the MCP server is that Starlette app. `custom_route`
covers the one non-MCP endpoint we need.
"""

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools import context

mcp = MCPServer(
    name="lifepilot",
    title="LifePilot",
    version="0.1.0",
    instructions=(
        "A family coordination agent. Ask it whether the week can actually be done by the people "
        "available, who should cover a pickup and why, and how to repair the week with the fewest "
        "changes. Every change it proposes needs a parent's approval before it takes effect."
    ),
)

_session_factory = None


def session_factory():
    """One factory for the process. Created on first use so tests can point it elsewhere."""
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


@mcp.tool(structured_output=True)
def get_family(speaker: str) -> dict[str, Any]:
    """Who is in the family, their roles, who can drive, and the places they travel between.

    Args:
        speaker: the name of the person talking, for example Dad, Mom, Aarav or Grandpa.
    """
    with session_factory()() as session:
        return context.get_family(session, speaker)


@mcp.tool(structured_output=True)
def get_schedule(speaker: str, start: date, end: date) -> dict[str, Any]:
    """Events and tasks between two dates, inclusive, as this speaker is allowed to see them.

    Args:
        speaker: the name of the person talking.
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
    """
    with session_factory()() as session:
        return context.get_schedule(session, speaker, start, end)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": mcp.name})


def build_app():
    return mcp.streamable_http_app(streamable_http_path="/mcp")


app = build_app()
