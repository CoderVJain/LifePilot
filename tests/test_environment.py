"""Phase 1: the installed SDK can satisfy hard requirements 1 and 2."""

from importlib.metadata import version


def test_mcp_sdk_imports_and_exposes_server():
    """Requirement 2: the SDK is importable and its server class is real, not a README claim."""
    from mcp.server.mcpserver import MCPServer

    assert callable(MCPServer)
    assert version("mcp").startswith("2.1")


def test_mcp_types_ship_2025_11_25_or_later():
    """Requirement 1: the wire versions we can negotiate include the minimum 2025-11-25."""
    import mcp_types

    assert hasattr(mcp_types, "_v2025_11_25")
    assert hasattr(mcp_types, "_v2026_07_28")
