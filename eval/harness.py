"""Run the real thing: words in, spoken answer out, nothing stubbed but the model's reply.

A real MCP server on a real socket, the real Strands client, the real agent, the real database. The
only substitution is that Bedrock's replies come from a cassette, so the same check costs one call
ever rather than one call per run.

This is the layer that was missing. Everything else tests a part; this tests the product.
"""

import os
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

import uvicorn

from eval.recorder import Cassette, key_for
from eval.transcripts import Exchange
from lifepilot_shared.llm import model_id


@dataclass
class Answered:
    """One exchange, run for real."""

    exchange: Exchange
    routed: str | None
    arguments: dict
    spoken: str
    debug: dict
    error: str | None = None


@contextmanager
def running_stack(cassette_name: str, live: bool):
    """A seeded server, a connected agent, and a cassette standing in for Bedrock."""
    # The same pinned day the tests use. Recorded model answers carry the date in their prompt, so
    # without this they would expire overnight and every CI run would want paying for.
    os.environ.setdefault("LIFEPILOT_TODAY", "2026-10-08")
    os.environ.pop("LIFEPILOT_WEEK", None)


    from eval.generate import build_demo_family
    from lifepilot import server as lifepilot_server
    from lifepilot.db.session import make_engine, make_session_factory

    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        build_demo_family(session)
    lifepilot_server._session_factory = factory

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(
        lifepilot_server.build_app(), host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("the MCP server did not start")
        time.sleep(0.05)

    from strands.tools.mcp import MCPClient

    from simulator.mcp_handshake import use_handshake_negotiation

    use_handshake_negotiation()
    client = MCPClient(url=f"http://127.0.0.1:{port}/mcp")

    cassette = Cassette(cassette_name, live=live)
    with client, _recorded_model(cassette):
        try:
            yield client, cassette
        finally:
            cassette.save()

    server.should_exit = True
    thread.join(timeout=10)
    lifepilot_server._session_factory = None


@contextmanager
def _recorded_model(cassette: Cassette):
    """Swap the agent's Bedrock call for one that replays, and records only when asked to."""
    from simulator import agent as agent_module

    original = agent_module.converse

    def recorded(**kwargs):
        model = model_id()
        tools = (kwargs.get("tool_config") or {}).get("tools")
        key = key_for(model, kwargs.get("system") or [], tools, kwargs["messages"])
        return cassette.respond(key, lambda: original(**kwargs))

    agent_module.converse = recorded
    try:
        yield
    finally:
        agent_module.converse = original


def answer(client, exchange: Exchange, state: dict | None = None) -> Answered:
    """Run one exchange through the whole stack.

    `state` is the conversation. Passing the previous exchange's state is what makes a follow-up a
    follow-up rather than a question out of nowhere.
    """
    from simulator import agent as agent_module
    from simulator.conversation import call_tool

    state = {} if state is None else state
    try:
        turn = agent_module.answer(client, exchange.speaker, exchange.said, call_tool, state)
    except LookupError as missing:
        return Answered(exchange, None, {}, "", {}, error=str(missing))
    except Exception as failure:  # noqa: BLE001 - the harness reports whatever happens
        return Answered(exchange, None, {}, "", {}, error=f"{type(failure).__name__}: {failure}")

    return Answered(
        exchange=exchange,
        # What the model chose, which is not always what ran: cannot_help executes nothing.
        routed=state.get("routed"),
        arguments=turn.debug.get("arguments") or {},
        spoken=turn.speak,
        debug=turn.debug,
    )
