"""The one non-voice step in LifePilot: signing in to Google once.

It runs on the MCP server rather than the simulator, because a Gmail token must never leave the
process that uses it. The browser is sent to Google, Google sends it back here with a code, and the
token is sealed into the database without passing through the agent, the page or a log.

Only `gmail.readonly` is ever requested, and what Google actually granted is checked before anything
is stored: a token carrying a wider scope is refused rather than quietly kept.
"""

import json
import os
import secrets

from lifepilot.mail.gmail import SCOPE
from lifepilot_shared.certs import trust_bundle

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

#: Must match a redirect URI registered on the OAuth client, exactly. 8931 is the MCP server.
DEFAULT_REDIRECT = "http://localhost:8931/oauth/callback"


class NotConfigured(RuntimeError):
    """The Google OAuth client is not set up in the environment."""


class WrongScope(RuntimeError):
    """Google granted something other than read-only Gmail. Nothing is stored."""


def redirect_uri() -> str:
    return (os.environ.get("GOOGLE_REDIRECT_URI") or "").strip() or DEFAULT_REDIRECT


def client_config() -> dict:
    """The OAuth client, built from the environment. No client_secrets.json on disk to leak."""
    client_id = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise NotConfigured(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set before Gmail can be linked."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri()],
        }
    }


def _flow(state: str | None = None, code_verifier: str | None = None):
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        client_config(),
        scopes=[SCOPE],
        redirect_uri=redirect_uri(),
        state=state,
        code_verifier=code_verifier,
    )
    # Same root cause as AWS_CA_BUNDLE: on a machine whose antivirus inspects HTTPS, requests uses
    # certifi and the token exchange fails on trust alone. The bundle trusts both chains.
    flow.oauth2session.verify = trust_bundle()
    return flow


def consent_url() -> tuple[str, str, str]:
    """Where to send the browser, the state to remember it by, and the PKCE verifier to keep.

    `access_type=offline` with `prompt=consent` is what yields a refresh token. Without it the link
    works until the first access token expires and then silently stops.

    The verifier has to come back out. `authorization_url` generates one and sends Google only its
    hash; the exchange must present the original, and a second `Flow` built for the callback has a
    different one. Google's answer to that is `invalid_grant: Missing code verifier`, which names
    the symptom and not the cause. Friction log 33.
    """
    flow = _flow(secrets.token_urlsafe(24))
    url, state = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    return url, state, flow.code_verifier


def token_from_code(code: str, state: str, code_verifier: str) -> dict:
    """Exchange the code for a token, refusing anything wider than read-only Gmail."""
    flow = _flow(state, code_verifier)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    granted = set(credentials.scopes or [])
    if granted - {SCOPE}:
        raise WrongScope(f"Google granted {sorted(granted)}; LifePilot only accepts {SCOPE}")
    if not credentials.refresh_token:
        raise WrongScope("Google returned no refresh token, so the link would last minutes")

    return json.loads(credentials.to_json())
