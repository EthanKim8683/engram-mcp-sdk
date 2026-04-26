"""FastMCP sub-server exposing Engram's three tools.

The module-level ``engram`` server can be mounted into a parent FastMCP
server::

    from fastmcp import FastMCP
    from engram_mcp_sdk import engram

    main = FastMCP("my-app")
    main.mount(engram, namespace="engram")

For test isolation, :func:`build_engram_server` constructs a fresh server
backed by an injected :class:`EngramClient`. The module-level ``engram``
just calls it with the default config.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from engram_mcp_sdk.client import (
    EngramClient,
    EngramServerError,
    UnauthorizedError,
)
from engram_mcp_sdk.config import Config, load_config
from engram_mcp_sdk.state import (
    State,
    clear_state,
    load_state,
    record_decline,
    record_token,
)
from engram_mcp_sdk.verify import run_localhost_verify_flow

logger = logging.getLogger(__name__)

VERIFY_TOOL_HINT = (
    "Engram's memory tools require a one-time World ID verification. "
    "Call the `verify_world_id` tool to walk the user through it. "
    "If the user has already declined, ask them whether they've changed "
    "their mind before calling `verify_world_id` again."
)


def _client_for(config: Config) -> EngramClient:
    return EngramClient(
        server_url=config.server_url,
        timeout_seconds=config.http_timeout_seconds,
    )


def _gate(state: State) -> None:
    """Raise a ``ToolError`` if the user is not (yet / any longer) verified."""

    if state.is_verified:
        return
    if state.has_declined:
        raise ToolError(
            "The user previously declined World ID verification, so "
            "Engram's memory tools are unavailable. " + VERIFY_TOOL_HINT
        )
    raise ToolError(
        "Engram's memory tools require World ID verification. "
        + VERIFY_TOOL_HINT
    )


def build_engram_server(
    *,
    config: Config | None = None,
    client_factory: Any = None,
) -> FastMCP:
    """Construct a FastMCP server with Engram's three tools.

    ``client_factory`` lets tests inject a fake :class:`EngramClient` (and a
    fake "open this URL in the browser" callback by way of the verify flow's
    ``open_browser`` flag, set when ``ENGRAM_VERIFY_OPEN_BROWSER=0``).
    """

    if config is None:
        config = load_config()
    factory = client_factory or (lambda: _client_for(config))

    mcp: FastMCP = FastMCP(
        name="engram",
        instructions=(
            "Engram is a long-term memory layer. Use `learn` to store a "
            "fact and `recall` to retrieve relevant facts; both require "
            "World ID verification (call `verify_world_id` to obtain it)."
        ),
    )

    @mcp.tool(
        description=(
            "Store a fact in the user's Engram memory. The content should be "
            "a concise, self-contained statement (one to three sentences) "
            "that will make sense out of context. Requires World ID "
            "verification."
        ),
    )
    async def learn(content: str) -> dict[str, Any]:
        state = load_state(config.state_path)
        _gate(state)
        client = factory()
        try:
            return await client.learn(
                access_token=state.access_token or "", content=content
            )
        except UnauthorizedError:
            clear_state(config.state_path)
            raise ToolError(
                "Engram's server rejected the cached access token. "
                + VERIFY_TOOL_HINT
            )
        except EngramServerError as exc:
            raise ToolError(
                f"engram-server returned {exc.status_code}: {exc.body!r}"
            ) from exc

    @mcp.tool(
        description=(
            "Search the user's Engram memory for facts relevant to a "
            "natural-language query. Returns up to `limit` matches "
            "(default 5). Requires World ID verification."
        ),
    )
    async def recall(query: str, limit: int = 5) -> dict[str, Any]:
        state = load_state(config.state_path)
        _gate(state)
        client = factory()
        try:
            return await client.recall(
                access_token=state.access_token or "",
                query=query,
                limit=limit,
            )
        except UnauthorizedError:
            clear_state(config.state_path)
            raise ToolError(
                "Engram's server rejected the cached access token. "
                + VERIFY_TOOL_HINT
            )
        except EngramServerError as exc:
            raise ToolError(
                f"engram-server returned {exc.status_code}: {exc.body!r}"
            ) from exc

    @mcp.tool(
        description=(
            "Walk the user through a one-time World ID verification by "
            "opening a localhost page in their default browser. The page "
            "runs the IDKit widget; on success Engram caches a long-lived "
            "access token on disk so the user never has to re-verify. The "
            "user can also click 'I'd rather not' to opt out -- subsequent "
            "calls to `learn` / `recall` will then explain that the tools "
            "are unavailable until they change their mind. Call this tool "
            "again if the user wants to retry after declining or after a "
            "previous verification was lost."
        ),
    )
    async def verify_world_id() -> dict[str, Any]:
        client = factory()
        try:
            result = await run_localhost_verify_flow(
                client=client,
                timeout_seconds=config.verify_timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise ToolError(
                f"Failed to run the verification flow: {exc!r}"
            ) from exc

        if result.status == "verified" and result.access_token:
            record_token(config.state_path, result.access_token)
            return {
                "status": "verified",
                "detail": result.detail,
            }
        if result.status == "declined":
            record_decline(config.state_path)
            return {
                "status": "declined",
                "detail": (
                    "Recorded the user's preference. Engram's memory tools "
                    "will refuse with a 'declined' message until the user "
                    "asks to verify again."
                ),
            }
        return {
            "status": result.status,
            "detail": result.detail,
            "url": result.url,
        }

    return mcp


# Module-level singleton, ready to be ``main.mount(engram, namespace="engram")``.
engram = build_engram_server()
