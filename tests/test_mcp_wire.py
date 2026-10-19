"""Hard requirements 1 and 2, proven on the wire rather than claimed in a README.

A real uvicorn server, a real Streamable HTTP client, a real initialize handshake. The negotiated
protocol version must be 2025-11-25 or later, and the tools must answer through it.
"""

import socket
import threading
import time
from datetime import timedelta

import pytest
import uvicorn
from mcp.client.client import Client

from eval.generate import MONDAY, build_demo_family
from lifepilot import server as lifepilot_server
from lifepilot.db.session import make_engine, make_session_factory

# The spec floor the rules set. String comparison is correct: these are ISO dates.
MINIMUM_PROTOCOL_VERSION = "2025-11-25"

# mode="legacy" is the SDK's name for the `initialize` handshake era, which tops out at 2025-11-25 --
# exactly the version the rules require. The default mode="auto" probes `server/discover` first, and
# that probe sends an `MCP-Protocol-Version` header; Avast corrupts any loopback response whose
# request carried one (friction log 7). The server is fine, and so is the SDK: this pins the one path
# that never sends the header, so the suite passes on this dev box.
HANDSHAKE = "legacy"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """A real LifePilot server on a real port, seeded with the demo family."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        build_demo_family(session)
    lifepilot_server._session_factory = factory

    port = _free_port()
    config = uvicorn.Config(lifepilot_server.build_app(), host="127.0.0.1", port=port, log_level="warning")
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


async def test_negotiated_protocol_version_is_2025_11_25_or_later(live_server):
    async with Client(live_server, mode=HANDSHAKE) as client:
        assert client.protocol_version >= MINIMUM_PROTOCOL_VERSION
        assert client.server_info.name == "lifepilot"


async def test_tools_are_listed_over_streamable_http(live_server):
    async with Client(live_server, mode=HANDSHAKE) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"get_family", "get_schedule"} <= names


async def test_get_family_answers_through_the_transport(live_server):
    async with Client(live_server, mode=HANDSHAKE) as client:
        result = await client.call_tool("get_family", {"speaker": "Dad"})
        family = result.structured_content
        assert family["speaker"]["role"] == "parent"
        assert {m["name"] for m in family["members"]} == {"Dad", "Mom", "Aarav", "Anaya", "Grandpa"}
        assert "football ground" in family["locations"]


async def test_a_child_sees_a_parents_work_as_busy(live_server):
    """Requirement #9, enforced by the tool layer and visible on the wire."""
    friday = MONDAY + timedelta(days=4)
    args = {"start": MONDAY.isoformat(), "end": friday.isoformat()}

    async with Client(live_server, mode=HANDSHAKE) as client:
        as_dad = (await client.call_tool("get_schedule", {"speaker": "Dad", **args})).structured_content
        as_aarav = (await client.call_tool("get_schedule", {"speaker": "Aarav", **args})).structured_content

    dad_work = [e for e in as_dad["events"] if e["title"] == "work"]
    assert dad_work and all(e["redacted"] is False for e in dad_work)

    assert not [e for e in as_aarav["events"] if e["title"] == "work"]
    assert [e for e in as_aarav["events"] if e["title"] == "Busy"]
    # Aarav still sees his own football practice in full.
    assert any(e["title"] == "football practice" and not e["redacted"] for e in as_aarav["events"])


async def test_a_caregiver_sees_only_what_is_assigned_to_them(live_server):
    friday = MONDAY + timedelta(days=4)
    args = {"start": MONDAY.isoformat(), "end": friday.isoformat()}

    async with Client(live_server, mode=HANDSHAKE) as client:
        as_grandpa = (
            await client.call_tool("get_schedule", {"speaker": "Grandpa", **args})
        ).structured_content

    # Grandpa drives nothing in the seeded week, so he sees nothing and no tasks.
    assert as_grandpa["events"] == []
    assert as_grandpa["tasks"] == []


def test_the_skills_extension_is_declared_in_the_capability_map():
    """SEP-2640 declared through SEP-2133 extension negotiation.

    Asserted on the server's own capability map rather than through the client, because the
    `legacy` handshake this dev box is pinned to (2025-11-25) does not surface
    `capabilities.extensions` -- extension negotiation arrived later, and the modern handshake is
    unusable here because Avast corrupts any response whose request carried an
    `MCP-Protocol-Version` header (friction log 7). The methods themselves are proven over the
    transport below, which is the part that matters.
    """
    extensions = lifepilot_server.mcp._lowlevel_server.get_capabilities().extensions or {}
    assert extensions["io.modelcontextprotocol/skills"] == {"directoryRead": False}


async def test_skills_list_and_get_answer_over_streamable_http(live_server):
    """The hand-built methods, on the wire. `mcp 2.1.1` has no skills module, so nothing in the
    SDK checks these shapes for us -- which is exactly why this is a wire test and not a README
    sentence."""
    from mcp_types import Request
    from pydantic import TypeAdapter

    class ListSkills(Request[dict, str]):
        method: str = "skills/list"
        params: dict = {}

    class GetSkill(Request[dict, str]):
        method: str = "skills/get"
        params: dict

    async with Client(live_server, mode=HANDSHAKE) as client:
        listed = await client.session.send_request(
            ListSkills(), TypeAdapter(dict)
        )
        assert listed["resultType"] == "complete"
        assert listed["skills"], "the server serves at least the LifePilot skill"

        entry = listed["skills"][0]
        assert entry["uri"] == "skill://lifepilot/SKILL.md"
        assert entry["frontmatter"]["name"] == "lifepilot"
        assert entry["resources"][0]["digest"].startswith("sha256:")

        got = await client.session.send_request(
            GetSkill(params={"uri": entry["uri"]}), TypeAdapter(dict)
        )

    assert got["skill"] == entry, "the SEP says identical in shape and meaning to a list entry"


async def test_a_skill_file_is_readable_as_an_ordinary_resource(live_server):
    """The baseline SEP-2640 rests on: a host that treats resources as a virtual filesystem reads
    an MCP-served skill exactly as it reads a local one."""
    async with Client(live_server, mode=HANDSHAKE) as client:
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert "skill://lifepilot/SKILL.md" in uris

        read = await client.read_resource("skill://lifepilot/SKILL.md")
        text = "".join(getattr(c, "text", "") for c in read.contents)

    assert text.startswith("---"), "the frontmatter a host parses and compares field by field"
    assert "name: lifepilot" in text
    assert "approve_proposal" in text, "the approval rule is the skill's whole point"
