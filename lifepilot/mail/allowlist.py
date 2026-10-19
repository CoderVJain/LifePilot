"""School senders only. The allowlist is built into every Gmail query and checked again on arrival.

Two layers on purpose. The query is what Google filters on; the check is what protects us when a
query is wrong, a thread carries a reply from elsewhere, or a sender spoofs a display name. A query
built without a sender filter is a bug, so there is no way to ask for one.
"""

import re
from datetime import date

ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class NoAllowlist(ValueError):
    """No school senders are set, so there is no safe query to run."""


def address_of(sender: str) -> str | None:
    """The bare address out of `Demo School <office@demo-school.invalid>`, lowercased."""
    found = ADDRESS.search(sender or "")
    return found.group(0).lower() if found else None


def clean(senders: list[str]) -> list[str]:
    """The allowlist as bare addresses, de-duplicated, in the order given."""
    seen: list[str] = []
    for entry in senders or []:
        address = address_of(entry)
        if address and address not in seen:
            seen.append(address)
    return seen


def permitted(sender: str, senders: list[str]) -> bool:
    """Whether a message that arrived may be read at all."""
    address = address_of(sender)
    return bool(address) and address in clean(senders)


def query(senders: list[str], after: date | None = None) -> str:
    """The Gmail search string. Always carries `from:(...)`; refuses to exist without one."""
    allowed = clean(senders)
    if not allowed:
        raise NoAllowlist("no school senders are set, so there is nothing LifePilot may read")

    parts = ["from:(" + " OR ".join(allowed) + ")"]
    if after is not None:
        parts.append(f"after:{after:%Y/%m/%d}")
    return " ".join(parts)
