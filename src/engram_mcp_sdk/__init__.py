"""Engram MCP SDK.

A drop-in FastMCP sub-server that augments any MCP server with two memory
tools (``learn`` / ``recall``) and a one-time identity-verification tool
(``verify_world_id``). Memory tools refuse to operate until the user has
verified their personhood with World ID; the verify tool spins up a localhost
page that runs IDKit, exchanges the resulting proof with engram-server for an
access token, and persists the token on disk so the user never has to verify
again.

Typical usage::

    from fastmcp import FastMCP
    from engram_mcp_sdk import engram

    mcp = FastMCP("my-app")
    mcp.mount(engram, namespace="engram")

The SDK can also be run standalone over stdio (``python -m engram_mcp_sdk``)
for users who only want the three tools as their entire MCP surface.
"""

from engram_mcp_sdk.server import build_engram_server, engram

__all__ = ["build_engram_server", "engram"]
