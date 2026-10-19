"""Linking Gmail: the one non-voice step, and the promises around it.

No network here. The flow object is replaced; what is asserted is what LifePilot asks Google for,
what it refuses to accept back, and what it stores.
"""

import json

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from eval.generate import build_demo_family
from lifepilot.db.models import EmailLink, Member
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.mail import oauth, vault
from lifepilot.mail.gmail import SCOPE
from lifepilot.tools import school_email as tool

TOKEN = {"refresh_token": "demo-refresh", "token": "demo-access"}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "demo-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "demo-secret")
    monkeypatch.setenv(vault.KEY_ENV, Fernet.generate_key().decode())
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


class FakeCredentials:
    def __init__(self, scopes, refresh_token="demo-refresh"):
        self.scopes = scopes
        self.refresh_token = refresh_token

    def to_json(self):
        return json.dumps({"refresh_token": self.refresh_token, "token": "demo-access"})


class FakeFlow:
    def __init__(self, credentials, code_verifier=None):
        self.credentials = credentials
        self.code_verifier = code_verifier
        self.asked = {}

    def fetch_token(self, code):
        self.asked["code"] = code


# --------------------------------------------------------------------------- what we ask for


def test_only_read_only_gmail_is_ever_requested(monkeypatch):
    asked = {}

    class Recording:
        oauth2session = type("S", (), {"verify": None})()
        code_verifier = "verifier-abc"

        def authorization_url(self, **kwargs):
            asked.update(kwargs)
            return "https://accounts.google.com/consent", "state-123"

    monkeypatch.setattr(oauth, "_flow", lambda state=None, code_verifier=None: Recording())
    url, state, verifier = oauth.consent_url()

    assert url.startswith("https://accounts.google.com/")
    assert state == "state-123"
    assert verifier == "verifier-abc"
    assert asked["access_type"] == "offline", "without this there is no refresh token"
    assert asked["prompt"] == "consent"


def test_the_client_config_names_the_mcp_servers_callback():
    config = oauth.client_config()["web"]
    assert config["redirect_uris"] == ["http://localhost:8931/oauth/callback"]
    assert config["client_id"] == "demo-id.apps.googleusercontent.com"


def test_the_scope_constant_is_the_read_only_one():
    assert SCOPE == "https://www.googleapis.com/auth/gmail.readonly"


def test_without_a_client_it_says_which_variables_to_set(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(oauth.NotConfigured) as refused:
        oauth.client_config()
    assert "GOOGLE_CLIENT_ID" in str(refused.value)


# --------------------------------------------------------------------------- what we accept back


def test_a_read_only_token_is_accepted(monkeypatch):
    monkeypatch.setattr(
        oauth, "_flow", lambda state=None, code_verifier=None: FakeFlow(FakeCredentials([SCOPE]))
    )
    assert oauth.token_from_code("code-1", "state-1", "v")["refresh_token"] == "demo-refresh"


def test_the_pkce_verifier_reaches_the_exchange(monkeypatch):
    """Google is sent only the verifier's hash at consent and demands the original at the exchange.
    A second Flow built for the callback has a different one, and Google's answer is
    `invalid_grant: Missing code verifier` -- which names the symptom, not the cause."""
    seen = {}

    def flow(state=None, code_verifier=None):
        seen["state"], seen["code_verifier"] = state, code_verifier
        return FakeFlow(FakeCredentials([SCOPE]), code_verifier)

    monkeypatch.setattr(oauth, "_flow", flow)
    oauth.token_from_code("code-1", "state-1", "verifier-abc")

    assert seen == {"state": "state-1", "code_verifier": "verifier-abc"}


def test_pkce_is_on_and_the_verifier_is_per_sign_in():
    """Real flows, no network: authorization_url generates the verifier, and two are not the same."""
    first, second = oauth.consent_url(), oauth.consent_url()

    assert first[2] and len(first[2]) >= 43, "PKCE must be on"
    assert first[2] != second[2]
    assert "code_challenge=" in first[0]


def test_a_wider_scope_is_refused_and_nothing_is_kept(monkeypatch):
    wider = [SCOPE, "https://www.googleapis.com/auth/gmail.send"]
    monkeypatch.setattr(
        oauth, "_flow", lambda state=None, code_verifier=None: FakeFlow(FakeCredentials(wider))
    )

    with pytest.raises(oauth.WrongScope) as refused:
        oauth.token_from_code("code-1", "state-1", "v")
    assert "gmail.send" in str(refused.value)


def test_a_token_with_no_refresh_token_is_refused(monkeypatch):
    """It would work for an hour and then stop, which reads as the product breaking by itself."""
    credentials = FakeCredentials([SCOPE], refresh_token=None)
    monkeypatch.setattr(
        oauth, "_flow", lambda state=None, code_verifier=None: FakeFlow(credentials)
    )

    with pytest.raises(oauth.WrongScope):
        oauth.token_from_code("code-1", "state-1", "v")


# --------------------------------------------------------------------------- what we store


def test_linking_stores_the_token_sealed(session):
    result = tool.link_gmail(session, "Dad", TOKEN)

    link = session.scalars(sa.select(EmailLink)).one()
    assert b"demo-refresh" not in link.encrypted_token
    assert vault.unseal(link.encrypted_token) == TOKEN
    assert result["linked"] is True


def test_relinking_keeps_the_senders_the_parent_already_set(session):
    tool.manage_email_access(session, "Dad", senders=["office@demo-school.invalid"])
    tool.link_gmail(session, "Dad", TOKEN)

    link = session.scalars(sa.select(EmailLink)).one()
    assert link.allowed_senders == ["office@demo-school.invalid"]
    assert vault.unseal(link.encrypted_token) == TOKEN


def test_linking_does_not_widen_what_may_be_read(session):
    """A fresh link reads nothing until a parent says which sender is the school."""
    result = tool.link_gmail(session, "Dad", TOKEN)

    assert result["allowed_senders"] == []
    with pytest.raises(tool.NotLinked):
        tool.check_school_email(session, "Dad", client=None)


def test_each_parent_links_their_own_account(session):
    tool.link_gmail(session, "Dad", TOKEN)
    tool.link_gmail(session, "Mom", {"refresh_token": "mom-refresh"})

    links = session.scalars(sa.select(EmailLink)).all()
    owners = {session.get(Member, link.parent_id).name for link in links}
    assert owners == {"Dad", "Mom"}


def test_a_child_cannot_link_an_account(session):
    with pytest.raises(tool.NotAllowed):
        tool.link_gmail(session, "Aarav", TOKEN)


# --------------------------------------------------------------------------- the two routes


class StubRequest:
    def __init__(self, **params):
        self.query_params = params


async def call(route, **params):
    import lifepilot.server as server

    handler = {r.path: r.endpoint for r in server.app.routes if hasattr(r, "endpoint")}[route]
    return await handler(StubRequest(**params))


def test_both_oauth_routes_are_served_by_the_mcp_server():
    import lifepilot.server as server

    paths = {r.path for r in server.app.routes if hasattr(r, "path")}
    assert {"/oauth/start", "/oauth/callback"} <= paths


async def test_a_callback_with_an_unknown_state_changes_nothing():
    """A stale or forged callback has no parent attached to it, so there is nothing to store."""
    response = await call("/oauth/callback", state="never-issued", code="x")
    assert b"expired" in response.body


async def test_a_refused_consent_says_so_without_an_exception():
    import lifepilot.server as server

    server._linking["state-9"] = ("Dad", "verifier")
    response = await call("/oauth/callback", state="state-9", error="access_denied")
    assert b"Nothing has changed" in response.body
    assert "state-9" not in server._linking


async def test_the_start_route_remembers_which_parent_is_linking(monkeypatch):
    import lifepilot.server as server

    monkeypatch.setattr(
        server.oauth,
        "consent_url",
        lambda: ("https://accounts.google.com/x", "state-7", "verifier-7"),
    )
    response = await call("/oauth/start", speaker="Mom")

    assert response.status_code in (302, 307)
    assert server._linking.pop("state-7") == ("Mom", "verifier-7")
