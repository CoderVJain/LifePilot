"""The MCP server. Streamable HTTP, spec 2025-11-25 or later, official SDK called at runtime.

`streamable_http_app()` returns a Starlette app whose lifespan already enters
`session_manager.run()`. Wrapping it in a FastAPI app would break that -- a mounted sub-app's lifespan
never runs, and every request would hang -- so the MCP server is that Starlette app. `custom_route`
covers the one non-MCP endpoint we need.
"""

import logging
from datetime import date
from html import escape
from typing import Any

from mcp.server.apps import APP_MIME_TYPE, Apps, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.resources import TextResource
from starlette.requests import Request
from starlette.responses import JSONResponse

from lifepilot.cards import PROPOSAL_HTML, PROPOSAL_URI
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.extensions.skills import Skills
from lifepilot.mail import oauth
from lifepilot.tools import add_event as _add
from lifepilot.tools import approve as _approve
from lifepilot.tools import cancel_event as _cancel
from lifepilot.tools import context
from lifepilot.tools import decide as _decide
from lifepilot.tools import fix_week as _fix
from lifepilot.tools import rules as _rules
from lifepilot.tools import scan_risks as _risk
from lifepilot.tools import school_email as _school
from lifepilot.tools import swap as _swap
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

# SEP-2640. Not in mcp 2.1.1, so it is served on the SDK's Extension framework:
# `skills/list` and `skills/get` are not spec methods, so they are legal bindings.
skills = Skills()

mcp = MCPServer(
    name="lifepilot",
    title="LifePilot",
    version="0.1.0",
    instructions=(
        "A family coordination agent. Ask it whether the week can actually be done by the people "
        "available, who should cover a pickup and why, and how to repair the week with the fewest "
        "changes. Every change it proposes needs a parent's approval before it takes effect."
    ),
    extensions=[apps, skills],
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

log = logging.getLogger("lifepilot")

_session_factory = None


def session_factory():
    """One factory for the process. Created on first use so tests can point it elsewhere."""
    global _session_factory
    if _session_factory is None:
        engine = make_engine()
        _warn_if_ephemeral(engine)
        _session_factory = make_session_factory(engine)
    return _session_factory


def _warn_if_ephemeral(engine) -> None:
    """Say so, loudly, when nothing written will outlive this process.

    `DATABASE_URL` unset means in-memory SQLite, which is right for tests and evals and wrong for
    anything a person does. A linked Gmail account, an approved change and a new event all vanish
    on restart, and the only symptom is being asked to link Gmail again -- which reads as the
    product forgetting rather than as a database that was never on disk.
    """
    # `url.database`, not the rendered string: SQLAlchemy percent-encodes the colons, so a URL for
    # `:memory:` renders as `%3Amemory%3A` and a substring check on it silently never matches. An
    # empty database with a SQLite driver is in-memory too.
    database = engine.url.database
    if engine.url.get_backend_name() != "sqlite" or database not in (None, "", ":memory:"):
        # render_as_string masks the password; str(url) would print it in cleartext.
        log.info("database: %s", engine.url.render_as_string(hide_password=True))
        return

    log.warning(
        "DATABASE_URL is not set, so this server is using in-memory SQLite. A linked Gmail "
        "account, approved changes and new events will all be gone when it restarts. For the "
        "demo set DATABASE_URL, for example sqlite+pysqlite:///demo.db"
    )


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
    speaker: str,
    start: date,
    end: date,
    about: str | None = None,
    at: str | None = None,
    title: str | None = None,
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
        title: one named thing they asked about, such as "piano" or "football". Set it for "what is
            the piano class timing", "when is football". Leave it out for a whole day or week.
    """
    with session_factory()() as session:
        return context.get_schedule(session, speaker, start, end, about, at, title)


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


@mcp.tool(structured_output=True, meta={"ui": {"resourceUri": PROPOSAL_URI}})
def add_event(
    ctx: Context,
    speaker: str,
    title: str,
    start: str,
    end: str | None = None,
    location: str | None = None,
    members: list[str] | None = None,
    needs_transport: bool = False,
    category: str = "other",
) -> dict[str, Any]:
    """Put something new in the week, once a parent approves it.

    This writes nothing on its own. It checks the new event against travel times and the family's
    rules, then returns a pending proposal; `approve_proposal` is what actually adds it.

    Args:
        speaker: the name of the person talking.
        title: what the event is called, such as "dentist" or "team meeting".
        start: when it starts, as YYYY-MM-DDTHH:MM.
        end: when it finishes, as YYYY-MM-DDTHH:MM. Defaults to an hour after it starts.
        location: an existing place in the family's list. Leave empty if they did not say.
        members: whose event it is. Defaults to the parent asking.
        needs_transport: true when somebody has to be driven there or collected.
        category: work, school, activity, appointment or other.
    """
    with session_factory()() as session:
        try:
            result = _add.add_event(
                session, speaker, title, start, end, location, members, needs_transport, category
            )
        except _add.NotAllowed as refused:
            return {"proposal_id": None, "status": "refused", "say": str(refused)}
        except _add.CannotAdd as unclear:
            return {"proposal_id": None, "status": "unclear", "say": str(unclear)}

    result["card"] = "proposal" if client_supports_apps(ctx) else None
    return result


@mcp.tool(structured_output=True, meta={"ui": {"resourceUri": PROPOSAL_URI}})
def cancel_event(
    ctx: Context,
    speaker: str,
    title: str | None = None,
    at: str | None = None,
    day: date | None = None,
    event_id: int | None = None,
    override: bool = False,
    replace_with: str | None = None,
    replace_members: list[str] | None = None,
) -> dict[str, Any]:
    """Take something out of the week, once a parent approves it.

    This writes nothing on its own. It works out what cancelling would free, which lifts nobody
    needs any more, and what it would strand, then returns a pending proposal; `approve_proposal`
    is what actually removes it. When more than one event answers to the words it asks which,
    rather than guessing.

    Args:
        speaker: the name of the person talking.
        title: what the event is called, such as "football practice" or "my meeting".
        at: when it starts, as YYYY-MM-DDTHH:MM, when they named a time rather than a name.
        day: the day it is on, as YYYY-MM-DD, to settle which one they mean.
        event_id: the exact event, when answering a "which one?" question.
        override: true only when the parent has said to cancel it anyway after being told a family
            rule pins it.
        replace_with: what to put in its place, when they said to book something instead. It takes
            the cancelled event's slot, and both legs are approved together or not at all.
        replace_members: who the replacement is for, besides the parent asking.
    """
    with session_factory()() as session:
        try:
            result = _cancel.cancel_event(
                session, speaker, title, at, event_id, day, override,
                replace_with, replace_members,
            )
        except _cancel.NotAllowed as refused:
            return {"proposal_id": None, "status": "refused", "say": str(refused)}

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


@mcp.tool(structured_output=True, meta={"ui": {"resourceUri": PROPOSAL_URI}})
def request_swap(
    speaker: str,
    partner: str,
    give_day: date | None = None,
    take_day: date | None = None,
    give_event_id: int | None = None,
    take_event_id: int | None = None,
) -> dict[str, Any]:
    """Offer to trade one of your lifts for one of the other parent's.

    Both halves are checked before anything is proposed, so a swap that would strand either parent
    is refused with the commitment or travel time that blocks it. Nothing changes until the other
    parent approves it in their own session.

    Args:
        speaker: the name of the person talking. Must be a parent.
        partner: the other parent being asked.
        give_day: the day whose lift the speaker is handing over.
        take_day: the day whose lift the speaker is taking on.
        give_event_id: the exact lift being handed over, when a day holds more than one.
        take_event_id: the exact lift being taken on, when a day holds more than one.
    """
    with session_factory()() as session:
        return _swap.request_swap(
            session, speaker, partner, give_day, take_day, give_event_id, take_event_id
        )


@mcp.tool(structured_output=True)
def list_proposals(speaker: str) -> dict[str, Any]:
    """What is waiting on someone's decision.

    Args:
        speaker: the name of the person talking.
    """
    with session_factory()() as session:
        return _approve.list_proposals(session, speaker)


@mcp.tool(structured_output=True, meta={"ui": {"resourceUri": PROPOSAL_URI}})
def check_school_email(ctx: Context, speaker: str) -> dict[str, Any]:
    """New email from the school, as dated tasks, with what they break and how to repair it.

    Only emails from the senders the parent allowed are read, and only on request. The result
    carries the task, the conflict and the proposed fix together, so one call answers the whole
    question. Nothing is written until `approve_proposal`.

    Args:
        speaker: the name of the person talking. Must be a parent.
    """
    with session_factory()() as session:
        try:
            result = _school.check_school_email(session, speaker)
        except (_school.NotAllowed, _school.NotLinked) as refused:
            return {"new_tasks": 0, "tasks": [], "say": str(refused)}

    result["card"] = "proposal" if client_supports_apps(ctx) else None
    return result


@mcp.tool(structured_output=True, meta={"ui": {"resourceUri": PROPOSAL_URI}})
def scan_risks(speaker: str, on: date | None = None) -> dict[str, Any]:
    """What is going to be missed, and a proposal for the time that would save it.

    Answers "what am I forgetting?". A deadline reminder fires when a task is due, which is too
    late to act on; this warns as soon as the free hours left stop being enough, counting the
    family's rules, and offers the first gap long enough to hold the work. Nothing is written until
    a parent approves it.

    Args:
        speaker: the name of the person talking. A child sees only their own tasks.
        on: the day to judge from. Defaults to today.
    """
    with session_factory()() as session:
        return _risk.scan_risks(session, speaker, on)


@mcp.tool(structured_output=True)
def name_task_child(speaker: str, proposal_id: int, child: str) -> dict[str, Any]:
    """Say which child a pending school task is for. This amends the proposal, it does not approve it.

    Use it when `check_school_email` came back with `needs_child`: the email named no child the
    family has, and there is more than one to choose between.

    Args:
        speaker: the name of the person talking. Must be a parent.
        proposal_id: the pending proposal from check_school_email.
        child: which child it is for, for example "Aarav".
    """
    with session_factory()() as session:
        try:
            return _school.name_task_child(session, speaker, proposal_id, child)
        except _school.NotAllowed as refused:
            return {"named": False, "say": str(refused)}


@mcp.tool(structured_output=True)
def manage_email_access(
    speaker: str, senders: list[str] | None = None, disconnect: bool = False
) -> dict[str, Any]:
    """Set which senders LifePilot may read, hear who they are, or disconnect email entirely.

    Disconnecting revokes the token with Google and deletes every stored school message.

    Args:
        speaker: the name of the person talking. Must be a parent.
        senders: the email addresses allowed, for example ["office@demo-school.invalid"]. Leave
            empty to hear the current list.
        disconnect: true for "disconnect my email".
    """
    with session_factory()() as session:
        try:
            return _school.manage_email_access(session, speaker, senders, disconnect)
        except _school.NotAllowed as refused:
            return {"linked": False, "say": str(refused)}


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": mcp.name})


# --------------------------------------------------------------------------- linking Gmail
#
# The only non-voice step in the product, and it lives here rather than in the simulator so that a
# Gmail token never enters the process running the agent. The browser goes to Google and comes back
# to this server; the token is sealed into the database and nothing else ever sees it.
#
# Which parent is linking, and the PKCE verifier for their exchange, remembered for the length of
# the round trip and keyed by the OAuth state Google hands back. One process, one family, one demo:
# a dict is the right size for that.
_linking: dict[str, tuple[str, str]] = {}


@mcp.custom_route("/oauth/start", methods=["GET"])
async def oauth_start(request: Request):
    """Send the parent to Google's consent screen."""
    from starlette.responses import RedirectResponse

    try:
        url, state, verifier = oauth.consent_url()
    except oauth.NotConfigured as missing:
        return _linking_page("Gmail is not set up", str(missing))

    _linking[state] = (request.query_params.get("speaker", "Dad"), verifier)
    return RedirectResponse(url)


@mcp.custom_route("/oauth/callback", methods=["GET"])
async def oauth_callback(request: Request):
    """Google's answer. Exchange it, store it sealed, and say so in one plain page."""
    state = request.query_params.get("state", "")
    started = _linking.pop(state, None)
    if started is None:
        return _linking_page("That link has expired", "Start again from the LifePilot page.")
    speaker, verifier = started
    if request.query_params.get("error"):
        return _linking_page("Not linked", "Google did not grant access. Nothing has changed.")

    try:
        token = oauth.token_from_code(request.query_params.get("code", ""), state, verifier)
    except (oauth.WrongScope, oauth.NotConfigured) as refused:
        return _linking_page("Not linked", str(refused))

    with session_factory()() as session:
        try:
            result = _school.link_gmail(session, speaker, token)
        except _school.NotAllowed as refused:
            return _linking_page("Not linked", str(refused))

    return _linking_page("Gmail linked", result["say"])


def _linking_page(heading: str, detail: str):
    """The whole non-voice surface of LifePilot: one sentence and an instruction to go back."""
    from starlette.responses import HTMLResponse

    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<title>LifePilot</title>"
        "<style>body{font:16px/1.6 system-ui;margin:4rem auto;max-width:34rem;padding:0 1rem}"
        "h1{font-size:1.4rem}</style>"
        f"<h1>{escape(heading)}</h1><p>{escape(detail)}</p>"
        "<p>You can close this tab and carry on speaking to LifePilot.</p>"
    )


def build_app():
    return mcp.streamable_http_app(streamable_http_path="/mcp")


app = build_app()
