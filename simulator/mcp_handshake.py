"""Make the Strands MCP client negotiate with the `initialize` handshake instead of probing.

By default Strands calls `negotiate_auto`, which first probes `server/discover` carrying an
`MCP-Protocol-Version` header. On a machine whose antivirus inspects loopback HTTP, that header makes
the proxy rewrite the reply into an invalid chunked response, and the client reports a closed
connection (docs/friction-log.md entries 7 and 9).

The handshake path never sends that header and answers over an event stream, which the proxy leaves
alone. It negotiates 2025-11-25 -- exactly the version the hackathon rules require -- so nothing is
given up by pinning it.

`MCPClient` exposes no setting for this, so we replace the module-level name it calls. That is a
deliberate reach into another package: `assert_patchable()` fails loudly if a Strands upgrade moves
it, rather than letting the client silently go back to probing.
"""

import logging

from mcp import ClientSession
from strands.tools.mcp import mcp_client

logger = logging.getLogger(__name__)

NEGOTIATE_ATTRIBUTE = "negotiate_session"


class StrandsLayoutChanged(RuntimeError):
    """Strands no longer looks the way this patch expects."""


async def _handshake_only(session: ClientSession) -> tuple[str | None, object | None]:
    """Negotiate with `initialize` alone. Same return shape as the function it replaces."""
    await session.initialize()
    return session.instructions, session.server_capabilities


def assert_patchable() -> None:
    """Check the thing we are about to replace is still there and still callable."""
    target = getattr(mcp_client, NEGOTIATE_ATTRIBUTE, None)
    if not callable(target):
        raise StrandsLayoutChanged(
            f"strands.tools.mcp.mcp_client.{NEGOTIATE_ATTRIBUTE} is missing or not callable. "
            "Strands has changed how it negotiates; re-check simulator/mcp_handshake.py."
        )


def use_handshake_negotiation() -> None:
    """Install the patch. Safe to call more than once."""
    assert_patchable()
    if getattr(mcp_client, NEGOTIATE_ATTRIBUTE) is _handshake_only:
        return
    setattr(mcp_client, NEGOTIATE_ATTRIBUTE, _handshake_only)
    logger.info("Strands MCP client pinned to the initialize handshake (2025-11-25)")
