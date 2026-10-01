"""The Strands MCP client can reach our server. Real socket, real port -- it fails no other way.

Without the patch this hangs and then fails on this dev box, because Strands probes `server/discover`
with an `MCP-Protocol-Version` header and the local antivirus corrupts the reply
(docs/friction-log.md entries 7 and 9).
"""

import socket
import threading
import time

import pytest
import uvicorn
from strands.tools.mcp import MCPClient

from eval.generate import build_demo_family
from lifepilot import server as lifepilot_server
from lifepilot.db.session import make_engine, make_session_factory
from simulator.mcp_handshake import assert_patchable, use_handshake_negotiation


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        build_demo_family(session)
    lifepilot_server._session_factory = factory

    port = _free_port()
    config = uvicorn.Config(
        lifepilot_server.build_app(), host="127.0.0.1", port=port, log_level="warning"
    )
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not uvicorn_server.started:
        if not thread.is_alive():
            raise RuntimeError("server thread died during startup")
        if time.monotonic() > deadline:
            raise TimeoutError("server did not start within 15 seconds")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"

    uvicorn_server.should_exit = True
    thread.join(timeout=10)
    lifepilot_server._session_factory = None


def test_the_patch_target_still_exists():
    """Fails loudly if a Strands upgrade moves what we replace, instead of silently reverting."""
    assert_patchable()


def test_strands_client_lists_our_tools(live_server):
    use_handshake_negotiation()
    client = MCPClient(url=live_server)
    with client:
        names = {tool.tool_name for tool in client.list_tools_sync()}
    assert {"get_family", "get_schedule"} <= names


def test_strands_client_calls_a_tool_and_gets_a_role_aware_answer(live_server):
    use_handshake_negotiation()
    client = MCPClient(url=live_server)
    with client:
        result = client.call_tool_sync("t1", "get_family", {"speaker": "Aarav"})

    assert result["status"] == "success"
    text = "".join(block.get("text", "") for block in result["content"])
    assert "Aarav" in text
    assert '"role": "child"' in text
