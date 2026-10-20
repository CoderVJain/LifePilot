"""The socket: who a session belongs to, and speaking first.

An Alexa+ MCP add-on receives an OAuth token for the linked account rather than a person, and has no
documented way to start a conversation (docs/alexa-platform-limits.md). So the session assumes the
account's parent, and the proactive side is a property of this simulator, labelled as one.
"""


from datetime import datetime

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from simulator.app import DEFAULT_SPEAKER


def test_a_session_belongs_to_somebody_from_the_first_word():
    """LifePilot used to open by asking who was there. Answering the first question straight away
    matters more than confirming an identity the platform will not give us anyway."""
    assert DEFAULT_SPEAKER == "Dad"

# --------------------------------------------------------------------------- speaking first


def test_the_browser_renders_a_message_nobody_asked_for():
    """The client dispatches on payload type with no correlation to a request, so an unsolicited
    reply is spoken like any other. This pins that the socket can in fact push one."""
    pushed = FastAPI()

    @pushed.websocket("/ws")
    async def handler(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({
            "type": "reply", "speak": "Aarav's football starts in 10 minutes.",
            "cards": [], "debug": {"model_calls": 0}, "proactive": "nudge",
        })
        try:
            await websocket.receive_json()
        except WebSocketDisconnect:
            return

    with TestClient(pushed).websocket_connect("/ws") as socket:
        pushed_message = socket.receive_json()

    assert pushed_message["proactive"] == "nudge"
    assert pushed_message["debug"]["model_calls"] == 0, "nothing on this path may cost money"


def test_what_to_say_reads_the_week_and_spends_nothing():
    """Two MCP reads, then pure computation. No model call, whatever comes back."""
    from simulator.app import _what_to_say

    calls = []
    soon = datetime.now().replace(microsecond=0)

    def fake_call_tool(mcp, tool, arguments):
        calls.append(tool)
        if tool == "get_schedule":
            return {"events": []}, {}
        return {"conflicts": []}, {}

    import simulator.app as app_module

    original = app_module.call_tool
    app_module.call_tool = fake_call_tool
    try:
        said = _what_to_say(None, "Dad", set())
    finally:
        app_module.call_tool = original

    assert calls == ["get_schedule", "detect_conflicts"]
    assert said == []
    assert soon <= datetime.now()


@pytest.mark.parametrize("label", ["spoke first — simulated", "reminder — simulated"])
def test_every_proactive_message_is_labelled(label):
    """Hard requirement 10: anything simulated says so. A real add-on cannot speak first."""
    import pathlib

    client = pathlib.Path("simulator/static/app.js").read_text(encoding="utf-8")
    assert "sim-badge" in client
    assert label in client, "both kinds carry a badge, and neither says it is a real notification"


def test_switching_speaker_clears_the_previous_session_from_screen():
    """#9 is a role view. Leaving Dad and Mom's turns readable in Aarav's session contradicts the
    privacy the server is enforcing underneath, on camera."""
    import pathlib

    client = pathlib.Path("simulator/static/app.js").read_text(encoding="utf-8")
    assert "function clearThread()" in client
    switcher = client.split('document.querySelectorAll(".speaker").forEach')[-1]
    assert "clearThread();" in switcher, "the switch itself has to clear it, not merely be able to"


# --------------------------------------------------------------------------- which hop failed

def test_a_dead_mcp_session_is_not_reported_as_a_model_problem():
    """`lifespan` opens one MCP session and holds it for the life of the process, so restarting the
    MCP server alone leaves it broken for good. Reporting that as "reaching the language model"
    sent two people into Bedrock credentials while the server was simply not running -- the second
    time costing half an hour. The hop that failed belongs in the answer.
    """
    from simulator.app import _why_degraded

    dead = RuntimeError(
        "the client session is not running. Ensure the agent is used within the MCP client "
        "context manager."
    )
    closed = RuntimeError("Tool execution failed: Connection to the MCP server was closed")

    for failure in (dead, closed):
        assert "planning server" in _why_degraded(failure)
        assert "language model" not in _why_degraded(failure)


def test_a_real_model_failure_still_says_so():
    """The new branch must not swallow the case it was carved out of."""
    from simulator.app import _why_degraded

    assert "language model" in _why_degraded(RuntimeError("ThrottlingException: rate exceeded"))
