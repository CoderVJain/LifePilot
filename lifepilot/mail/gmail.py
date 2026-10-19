"""Reading the school's email, and nothing else.

Two clients with the same shape: `GmailClient` talks to Google, `FakeGmail` serves messages from a
list. Every test and eval uses the fake, so the suite stays free and offline.

The scope is read-only and there is no code path that sends, modifies or deletes. Google enforces
that for us: even a stolen token cannot do those things.
"""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime

from lifepilot.mail.allowlist import permitted
from lifepilot_shared.certs import trust_bundle

#: The only scope LifePilot ever asks for. Anything wider is a bug, not a configuration choice.
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

REVOKE_URL = "https://oauth2.googleapis.com/revoke"


@dataclass(frozen=True)
class RawMessage:
    """One email, in memory only. Nothing of `subject` or `body` is ever stored or logged."""

    id: str
    sender: str
    received_at: datetime
    subject: str
    body: str


class GmailClient:
    """Google's Gmail API, read-only.

    The certificate bundle is passed in explicitly, for the same reason `llm.py` passes one to
    boto3: on a machine whose antivirus inspects HTTPS, a client that resolves its own trust store
    fails with `CERTIFICATE_VERIFY_FAILED`. This is a third transport with a third trust store --
    `googleapiclient` talks through `httplib2`, which takes neither `AWS_CA_BUNDLE` nor
    `REQUESTS_CA_BUNDLE` and has no environment variable of its own, so nothing but the argument
    will do. Avast intercepts some processes and not others, so without this the demo works in one
    terminal and fails in the next (friction log 34).
    """

    def __init__(self, token: dict):
        import google_auth_httplib2
        import httplib2
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        self._credentials = Credentials.from_authorized_user_info(token, [SCOPE])
        # The same http carries the refresh, so the token exchange is covered as well as the reads.
        authorized = google_auth_httplib2.AuthorizedHttp(
            self._credentials, http=httplib2.Http(ca_certs=trust_bundle())
        )
        self._api = build("gmail", "v1", http=authorized, cache_discovery=False)

    def search(self, query: str, senders: list[str], limit: int = 10) -> list[RawMessage]:
        """Messages matching the query, with every sender checked again on arrival."""
        listed = (
            self._api.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
            .get("messages", [])
        )
        found = []
        for stub in listed:
            raw = self._api.users().messages().get(userId="me", id=stub["id"], format="full").execute()
            message = _parse(raw)
            if permitted(message.sender, senders):
                found.append(message)
        return found

    def revoke(self) -> None:
        """Tell Google the token is finished with. Revoking the refresh token kills every access
        token issued from it, so this is the whole disconnection, not half of it."""
        import requests
        from google.auth.transport.requests import Request

        # A fourth transport, a fourth trust store. Same reason as the constructor's.
        session = requests.Session()
        session.verify = trust_bundle()

        Request(session)(
            REVOKE_URL,
            method="POST",
            body=f"token={self._credentials.refresh_token}".encode(),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )


class FakeGmail:
    """The same shape, from a list of dicts. Used by every test and eval."""

    def __init__(self, messages: list[dict]):
        self.messages = messages
        self.queries: list[str] = []
        self.revoked = False

    def search(self, query: str, senders: list[str], limit: int = 10) -> list[RawMessage]:
        self.queries.append(query)
        found = [
            RawMessage(
                id=m.get("id", f"fake-{i}"),
                sender=m["sender"],
                received_at=m.get("received_at") or datetime(2026, 10, 7, 9, 0),
                subject=m.get("subject", ""),
                body=m.get("body", ""),
            )
            for i, m in enumerate(self.messages)
        ]
        return [m for m in found if permitted(m.sender, senders)][:limit]

    def revoke(self) -> None:
        self.revoked = True


# --------------------------------------------------------------------------- parsing


def _parse(raw: dict) -> RawMessage:
    headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
    received = datetime.fromtimestamp(int(raw.get("internalDate", 0)) / 1000, UTC)
    return RawMessage(
        id=raw["id"],
        sender=headers.get("from", ""),
        received_at=received.replace(tzinfo=None),
        subject=headers.get("subject", ""),
        body=_text(raw.get("payload", {})),
    )


def _text(payload: dict) -> str:
    """The plain-text body. Attachments are never downloaded: this only reads inline parts."""
    if payload.get("mimeType") == "text/plain":
        return _decode(payload.get("body", {}).get("data", ""))
    for part in payload.get("parts", []):
        found = _text(part)
        if found:
            return found
    return ""


def _decode(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
