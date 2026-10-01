"""The MCP server. Streamable HTTP, spec 2025-11-25 or later, official SDK called at runtime.

`streamable_http_app()` returns a Starlette app whose lifespan already enters
`session_manager.run()`. Wrapping it in a FastAPI app would break that -- a mounted sub-app's lifespan
never runs, and every request would hang -- so the MCP server is that Starlette app. `custom_route`
covers the one non-MCP endpoint we need.
"""

from datetime import date
from typing import Any

from mcp.server.apps import APP_MIME_TYPE, Apps, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.resources import TextResource
from starlette.requests import Request
from starlette.responses import JSONResponse

from lifepilot.cards import PROPOSAL_HTML, PROPOSAL_URI
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools import approve as _approve
from lifepilot.tools import context
from lifepilot.tools import decide as _decide
from lifepilot.tools import fix_week as _fix
from lifepilot.tools import rules as _rules
from lifepilot.tools import what_if as _whatif
from lifepilot.tools.detect_conflicts import detect_conflicts as _detect_conflicts

# MCP Apps is additive on purpose. A client that never negotiated it still gets the same structured
# result and the same spoken sentence; it just loses the buttons.
#
# The extension serves the `ui://` resource and advertises the capability, but `fix_week` is
# registered as an ordinary tool carrying `_meta.ui.resourceUri` rather than through `@apps.tool`.
# Extension-contributed tools are hidden from clients that did not negotiate the extension, and
# measuring it showed `fix_week` missing from `tools/list` for exactly the clients we use -- the
# headline feature invisible to the agent that needs it. Carrying the meta on a core tool gives
# Apps-aware hosts the same wire format and everyone else the tool.
apps = Apps()

mcp = MCPServer(
    name="lifepilot",
    title="LifePilot",
    version="0.1.0",
    instructions=(
        "A family coordination agent. Ask it whether the week can actually be done by the people "
        "available, who should cover a pickup and why, and how to repair the week with the fewest "
        "changes. Every change it proposes needs a parent's approval before it takes effect."
    ),
    extensions=[apps],
)

apps.add_html_resource(
    PROPOSAL_URI,
    PROPOSAL_HTML,
    name="proposal",
    title="Proposed changes",
    description="The changes LifePilot suggests, with Approve and Not now.",
)

# The same document as an ordinary resource. An extension's resources are served only to clients that
# negotiated the extension, and our own host is not one of them, so without this it could not fetch
# the card it is meant to render.
mcp.add_resource(
    TextResource(
        uri=PROPOSAL_URI,
        name="proposal",
        title="Proposed changes",
        description="The changes LifePilot suggests, with Approve and Not now.",
        mime_type=APP_MIME_TYPE,
        text=PROPOSAL_HTML,
    )
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
def get_schedule(
    speaker: str, start: date, end: date, about: str | None = None, at: str | None = None
) -> dict[str, Any]:
    """Events and tasks between two dates, inclusive, as this speaker is allowed to see them.

    Args:
        speaker: the name of the person talking.
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
        about: whose day they asked about. The speaker's own name for "my schedule" or "what have
            I got", another family member's name for "Aarav's school timing". Leave empty for
            "what's happening this week", which is about everyone.
        at: a single moment they asked about, as HH:MM or YYYY-MM-DDTHH:MM. Set it for "do I have
            anything at five", "am I free at four". Leave it out for a whole day or week.
    """
    with session_factory()() as session:
        return context.get_schedule(session, speaker, start, end, about, at)


@mcp.tool(structured_output=True)
def detect_conflicts(speaker: str, start: date, end: date) -> dict[str, Any]:
    """What is actually broken in the week: a lift nobody eligible can make, a clash, a broken rule.

    This is not an overlap check. It counts travel time, who can drive and the family's own rules,
    so it finds a pickup that cannot be made even when no two events overlap.

    Args:
        speaker: the name of the person talking.
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
    """
    with session_factory()() as session:
        return _detect_conflicts(session, speaker, start, end)


@mcp.tool(structured_output=True)
def add_rule(
    speaker: str, rule_type: str, params: dict[str, Any], spoken_text: str, confirmed: bool = False
) -> dict[str, Any]:
    """Remember a family rule. Call once to hear it read back, again with confirmed=true to store it.

    Only these five types exist: immovable_event, latest_end, buffer_after, eligibility,
    load_balance. If what was said fits none of them, this refuses and explains; do not reshape the
    request to fit. Only a parent may add a rule.

    Args:
        speaker: the name of the person talking.
        rule_type: one of the five supported types.
        params: the details for that type, for example {"category": "study", "latest_end": "21:00"}.
        spoken_text: what the parent actually said, kept word for word.
        confirmed: true only after the parent has heard it read back and agreed.
    """
    with session_factory()() as session:
        try:
            return _rules.add_rule(session, speaker, rule_type, params, spoken_text, confirmed)
        except _rules.NotAllowed as refused:
            return {"stored": False, "needs_confirmation": False, "say": str(refused)}


@mcp.tool(structured_output=True)
def list_rules(speaker: str) -> dict[str, Any]:
    """Every family rule currently in force, in the family's words and in LifePilot's.

    Args:
        speaker: the name of the person talking.
    """
    with session_factory()() as session:
        return _rules.list_rules(session, speaker)


@mcp.tool(structured_output=True)
def remove_rule(speaker: str, rule_id: int, confirmed: bool = False) -> dict[str, Any]:
    """Retire a family rule. Call once to hear it read back, again with confirmed=true to drop it.

    Args:
        speaker: the name of the person talking.
        rule_id: the id of the rule, from list_rules.
        confirmed: true only after the parent has heard it read back and agreed.
    """
    with session_factory()() as session:
        try:
            return _rules.remove_rule(session, speaker, rule_id, confirmed)
        except _rules.NotAllowed as refused:
            return {"removed": False, "say": str(refused)}


@mcp.tool(structured_output=True)
def suggest_responsible(
    speaker: str, start: date, end: date, title: str | None = None, event_id: int | None = None
) -> dict[str, Any]:
    """Who should cover a lift, ranked, with the reason each one beat the next.

    The ranking is the server's, not the model's: availability, travel time, current load and the
    family's own rules, in that order. Say the reason as given.

    Args:
        speaker: the name of the person talking.
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
        title: the event the lift is for, for example "football".
        event_id: the event id, if known, instead of the title.
    """
    with session_factory()() as session:
        return _decide.suggest_responsible(session, speaker, start, end, event_id, title)


@mcp.tool(structured_output=True)
def explain_choice(
    speaker: str,
    person: str,
    start: date,
    end: date,
    title: str | None = None,
    event_id: int | None = None,
) -> dict[str, Any]:
    """Why this person was chosen for a lift, or why not. Answers "why not Grandpa?".

    The answer is the reason recorded when the decision was made, so it always matches it.

    Args:
        speaker: the name of the person talking.
        person: who is being asked about, for example "Grandpa".
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
        title: the event the lift is for.
        event_id: the event id, if known, instead of the title.
    """
    with session_factory()() as session:
        return _decide.explain_choice(session, speaker, start, end, person, event_id, title)


@mcp.tool(structured_output=True, meta={"ui": {"resourceUri": PROPOSAL_URI}})
def fix_week(ctx: Context, speaker: str, start: date, end: date) -> dict[str, Any]:
    """Repair the week with the fewest possible changes, and hold it for a parent to approve.

    Immovable events never move and nothing that already works is touched. This changes nothing on
    its own: it returns a diff awaiting approval.

    Args:
        speaker: the name of the person talking.
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
    """
    with session_factory()() as session:
        try:
            result = _fix.fix_week(session, speaker, start, end)
        except _fix.NotAllowed as refused:
            return {"needed": False, "solved": False, "say": str(refused)}

    # The card is support, never the answer. Saying so in the result keeps a text-only client from
    # waiting for buttons that are never coming.
    result["card"] = "proposal" if client_supports_apps(ctx) else None
    return result


@mcp.tool(structured_output=True)
def what_if(speaker: str, start: date, end: date, change: dict[str, Any]) -> dict[str, Any]:
    """Try a change without making it: what would break, and what would fix it.

    This never alters anything. Use it for "what if my four o'clock runs late", "can I say yes to a
    six o'clock on Friday", or "what if football is cancelled".

    Args:
        speaker: the name of the person talking.
        start: first day of the window, as YYYY-MM-DD.
        end: last day of the window, as YYYY-MM-DD.
        change: one of
            {"kind": "runs_late", "title": "performance review", "until": "17:30"},
            {"kind": "new_event", "title": "6pm meeting", "start": "2026-10-09T18:00",
             "end": "2026-10-09T19:00"},
            {"kind": "cancelled", "title": "football practice"}.
    """
    with session_factory()() as session:
        return _whatif.what_if(session, speaker, start, end, change)


@mcp.tool(structured_output=True)
def approve_proposal(speaker: str, proposal_id: int) -> dict[str, Any]:
    """Carry out a proposed change. This is the only thing that alters the family's plan.

    Args:
        speaker: the name of the person talking. Must be a parent, or the person the proposal names.
        proposal_id: the proposal to approve.
    """
    with session_factory()() as session:
        try:
            return _approve.approve_proposal(session, speaker, proposal_id)
        except (_approve.NotAllowed, _approve.CannotApply) as refused:
            return {"approved": False, "proposal_id": proposal_id, "say": str(refused)}


@mcp.tool(structured_output=True)
def reject_proposal(speaker: str, proposal_id: int) -> dict[str, Any]:
    """Decline a proposed change. Nothing is altered.

    Args:
        speaker: the name of the person talking.
        proposal_id: the proposal to reject.
    """
    with session_factory()() as session:
        try:
            return _approve.reject_proposal(session, speaker, proposal_id)
        except (_approve.NotAllowed, _approve.CannotApply) as refused:
            return {"rejected": False, "proposal_id": proposal_id, "say": str(refused)}


@mcp.tool(structured_output=True)
def list_proposals(speaker: str) -> dict[str, Any]:
    """What is waiting on someone's decision.

    Args:
        speaker: the name of the person talking.
    """
    with session_factory()() as session:
        return _approve.list_proposals(session, speaker)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": mcp.name})


def build_app():
    return mcp.streamable_http_app(streamable_http_path="/mcp")


app = build_app()
