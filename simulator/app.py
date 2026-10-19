"""The simulated Alexa+ experience: serves the page and holds the conversation.

The browser stays thin. It sends text and renders what comes back; every decision happens here or in
the MCP server. One WebSocket per browser tab, one speaker per message, so switching speaker is a
different session with a different view of the family.

This increment routes a small fixed set of utterances straight to MCP tools. The Strands agent and
Bedrock replace that router in a later increment; the transport, the role handling and the debug
channel are the same either way.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from strands.tools.mcp import MCPClient

from lifepilot_shared.llm import InterceptedHTTPS
from lifepilot_shared.week import demo_span
from simulator import agent
from simulator.conversation import Turn, call_tool, respond
from simulator.mcp_handshake import use_handshake_negotiation
from simulator.reminders import due_now

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8931/mcp")

# LIFEPILOT_LLM=0 answers from the keyword router instead of Bedrock: free, offline, and the baseline
# experiments 1-4 compare against.
USE_LLM = os.environ.get("LIFEPILOT_LLM", "1") != "0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One MCP connection for the process, opened once and held.

    use_handshake_negotiation() must run before the client connects: see
    docs/friction-log.md entry 10.
    """
    use_handshake_negotiation()
    client = MCPClient(url=MCP_SERVER_URL)
    client.start()
    app.state.mcp = client
    logger.info(
        "connected to MCP server at %s (model path: %s)",
        MCP_SERVER_URL,
        "Bedrock Nova Micro" if USE_LLM else "keyword router",
    )
    try:
        yield
    finally:
        client.stop(None, None, None)


app = FastAPI(title="LifePilot simulator", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/link-gmail")
async def link_gmail(speaker: str = "Dad"):
    """Hand the browser over to the MCP server, which owns the whole OAuth round trip.

    The simulator never sees the code or the token: it only knows where the MCP server is, and the
    browser goes there directly. That is the one place this redirect earns its keep -- the page
    would otherwise have to be told the MCP server's address.
    """
    from urllib.parse import quote, urlsplit
    origin = urlsplit(MCP_SERVER_URL)
    return RedirectResponse(f"{origin.scheme}://{origin.netloc}/oauth/start?speaker={quote(speaker)}")


# Only these may be reached from inside a card. A card is untrusted content in a sandboxed frame, so
# the host decides what it can do, and the list is short on purpose: decide a proposal, nothing else.
CARD_TOOLS = {"approve_proposal", "reject_proposal"}


@app.get("/card/{name}", response_class=HTMLResponse)
async def card(name: str) -> HTMLResponse:
    """Serve an MCP App document, fetched from the MCP server rather than kept here."""
    if name != "proposal":
        raise HTTPException(status_code=404, detail="no such card")
    html = await run_in_threadpool(_read_card, app.state.mcp)
    return HTMLResponse(html)


def _read_card(mcp) -> str:
    for item in mcp.read_resource_sync("ui://lifepilot/proposal.html").contents:
        text = getattr(item, "text", None)
        if text:
            return text
    raise HTTPException(status_code=502, detail="the card could not be loaded")


#: Who LifePilot could be talking to. Asked at the start of every session because the platform will
#: not say: an Alexa+ MCP add-on is given an OAuth token for the linked account, not a person. See
#: docs/alexa-platform-limits.md.
#: How often the proactive loop looks for something to say. Slow on purpose: nothing it says is
#: urgent to the second, and every tick is a pair of MCP calls.
TICK_SECONDS = 30

#: Who a session belongs to until the switcher says otherwise. An Alexa+ MCP add-on is handed an
#: OAuth token for the linked account rather than a person (docs/alexa-platform-limits.md), so the
#: account's parent is assumed. LifePilot used to open by asking who was there; it answers straight
#: away instead, because a question before every first request is a tax on every single session.
DEFAULT_SPEAKER = "Dad"


@app.websocket("/ws")
async def conversation(websocket: WebSocket) -> None:
    await websocket.accept()
    # Conversation state for this socket. The browser keeps one socket and sends the speaker with
    # each message, so anything half-finished is held per speaker inside.
    state: dict = {"spoken_already": set(), "speaker": DEFAULT_SPEAKER}

    watching = asyncio.create_task(_speak_first(websocket, state))
    try:
        while True:
            message = await websocket.receive_json()
            text = (message.get("text") or "").strip()
            if not text and message.get("type") != "card_call":
                continue

            mcp = websocket.app.state.mcp

            if message.get("type") == "card_call":
                await _card_call(websocket, mcp, state["speaker"], message)
                continue

            speaker = message.get("speaker") or state["speaker"]
            state["speaker"] = speaker

            turn = await _answer(mcp, speaker, text, state)
            await websocket.send_json(_as_payload(turn))
    except WebSocketDisconnect:
        return
    finally:
        watching.cancel()


async def _speak_first(websocket: WebSocket, state: dict) -> None:
    """Say something nobody asked for: a plan about to break, or something about to start.

    A real Alexa+ add-on cannot do this -- there is no documented server-initiated push -- so this is
    a property of the simulator and is labelled as one in the UI. No model call happens on this path;
    every sentence comes from a template, because a timer pointed at Bedrock bills for as long as the
    page is open.
    """
    while True:
        await asyncio.sleep(TICK_SECONDS)
        speaker = state.get("speaker")
        if not speaker:
            continue
        try:
            for item in await run_in_threadpool(_what_to_say, websocket.app.state.mcp, speaker,
                                                state["spoken_already"]):
                state["spoken_already"].add(item.key)
                await websocket.send_json({
                    "type": "reply", "speak": item.speak, "cards": [],
                    "debug": {"tool": "reminders", "model_calls": 0, "estimated_cost_usd": 0.0},
                    "proactive": item.kind,
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            # Nobody is watching this loop, so a bad tick must not end it.
            logger.exception("the proactive check failed; carrying on")


def _what_to_say(mcp, speaker: str, already_said: set) -> list:
    """One pair of MCP reads, then pure computation. Runs off the event loop."""
    start, end = demo_span()
    window = {"speaker": speaker, "start": start.isoformat(), "end": end.isoformat()}
    schedule, _ = call_tool(mcp, "get_schedule", {**window, "about": speaker})
    conflicts, _ = call_tool(mcp, "detect_conflicts", window)
    return due_now(schedule, conflicts, datetime.now(), already_said)


async def _answer(mcp, speaker: str, text: str, state: dict) -> Turn:
    """Answer the turn, falling back to the keyword router if the model is unreachable.

    Bedrock can fail for reasons that have nothing to do with the family's week: an expired
    credential, a rate limit, or -- on this dev box -- antivirus rejecting the certificate. None of
    those are a reason to drop the conversation mid-demo, and every tool still works without the
    model. The fallback understands fewer phrasings and says so.
    """
    if not USE_LLM:
        return await run_in_threadpool(respond, mcp, speaker, text)

    try:
        return await run_in_threadpool(agent.answer, mcp, speaker, text, call_tool, state)
    except Exception as failure:
        logger.exception("the model path failed; answering from the keyword router instead")
        turn = await run_in_threadpool(respond, mcp, speaker, text)
        # Say it out loud. Silently dropping to a handful of set phrases looks like the product
        # simply failed to understand a reasonable question, and sends you hunting in the wrong
        # place: the first report of this was "it gave me the help text", not "AWS is unreachable".
        turn.speak = f"{_why_degraded(failure)} {turn.speak}"
        turn.debug = {**turn.debug, "note": f"fell back to the keyword router: {failure}"}
        return turn


def _why_degraded(failure: Exception) -> str:
    if isinstance(failure, InterceptedHTTPS):
        return "I cannot reach the language model, so I am only following a few set phrases."
    return "Something went wrong reaching the language model, so I am on the simple phrases only."


async def _card_call(websocket: WebSocket, mcp, speaker: str, message: dict) -> None:
    """A button inside a card asking the host to make a call. The host decides whether it may."""
    tool = message.get("tool")
    if tool not in CARD_TOOLS:
        await websocket.send_json(
            {"type": "card_result", "request_id": message.get("request_id"),
             "error": f"a card may not call {tool}"}
        )
        return

    arguments = {"speaker": speaker, **(message.get("arguments") or {})}
    data, debug = await run_in_threadpool(call_tool, mcp, tool, arguments)
    await websocket.send_json(
        {
            "type": "card_result",
            "request_id": message.get("request_id"),
            "result": data,
            "debug": debug,
        }
    )


def _as_payload(turn: Turn) -> dict:
    return {
        "type": "reply",
        "speak": turn.speak,
        "cards": turn.cards,
        "debug": turn.debug,
    }


class RevalidatingStatic(StaticFiles):
    """Static files the browser must revalidate on every load.

    A cached `app.js` survived a server restart and a reload, so the page kept rendering the old
    card while the server served the new one -- half an hour of chasing a fixed bug. On video day
    that is a stale demo on camera. These files are local and tiny, so revalidating costs nothing.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", RevalidatingStatic(directory=STATIC_DIR), name="static")
