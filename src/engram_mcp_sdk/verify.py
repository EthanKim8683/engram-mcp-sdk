"""Localhost browser flow for World ID verification.

When ``run_localhost_verify_flow`` is called, the SDK:

1. Picks a free port on 127.0.0.1 and binds a tiny Starlette app.
2. Serves the static IDKit page from :mod:`engram_mcp_sdk.verify_page` and
   proxies its three RPC endpoints (``/idkit-config``, ``/proof``,
   ``/decline``) to engram-server / local state.
3. Opens the user's default browser at that URL.
4. Awaits the page reporting either "verified", "declined", or a timeout.
5. Tears down the server and returns the outcome.

The flow never blocks the MCP host process itself: ``uvicorn`` runs in the
background asyncio loop, and the browser is launched via ``webbrowser`` (no
shelling out to system commands). On headless boxes ``webbrowser.open``
returns ``False`` and the caller falls back to printing the URL.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import webbrowser
from dataclasses import dataclass
from typing import Any, Literal

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from engram_mcp_sdk.client import EngramClient, EngramServerError
from engram_mcp_sdk.verify_page import VERIFY_HTML

logger = logging.getLogger(__name__)

VerifyStatus = Literal["verified", "declined", "timeout", "error"]


@dataclass
class VerifyResult:
    status: VerifyStatus
    detail: str
    access_token: str | None = None
    url: str | None = None  # the localhost URL we opened (handy for headless)


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def build_verify_app(
    *,
    client: EngramClient,
    on_done: "asyncio.Future[VerifyResult]",
) -> Starlette:
    """Construct the localhost Starlette app. Exposed for unit tests."""

    async def index(_request: Request) -> Response:
        return HTMLResponse(VERIFY_HTML)

    async def get_idkit_config(_request: Request) -> Response:
        try:
            cfg = await client.fetch_idkit_config()
        except EngramServerError as exc:
            return JSONResponse(
                {"error": str(exc), "body": exc.body},
                status_code=502,
            )
        return JSONResponse(
            {
                "app_id": cfg.app_id,
                "action": cfg.action,
                "rp_context": cfg.rp_context,
            }
        )

    async def post_proof(request: Request) -> Response:
        proof = await request.json()
        try:
            access_token = await client.exchange_proof_for_token(proof)
        except EngramServerError as exc:
            return JSONResponse(
                {"error": str(exc), "body": exc.body},
                status_code=exc.status_code,
            )
        if not on_done.done():
            on_done.set_result(
                VerifyResult(
                    status="verified",
                    detail="World ID proof exchanged for access token.",
                    access_token=access_token,
                )
            )
        return JSONResponse({"status": "verified"})

    async def post_decline(_request: Request) -> Response:
        if not on_done.done():
            on_done.set_result(
                VerifyResult(
                    status="declined",
                    detail="User declined to verify with World ID.",
                )
            )
        return JSONResponse({"status": "declined"})

    return Starlette(
        routes=[
            Route("/", index),
            Route("/idkit-config", get_idkit_config),
            Route("/proof", post_proof, methods=["POST"]),
            Route("/decline", post_decline, methods=["POST"]),
        ]
    )


async def run_localhost_verify_flow(
    *,
    client: EngramClient,
    timeout_seconds: float,
    open_browser: bool = True,
    port: int | None = None,
) -> VerifyResult:
    """Spin up the localhost page, open the browser, await user action."""

    chosen_port = port or _free_port()
    url = f"http://127.0.0.1:{chosen_port}/"

    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()

    app = build_verify_app(client=client, on_done=done)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=chosen_port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for uvicorn to actually bind before opening the browser.
    while not server.started and not server_task.done():
        await asyncio.sleep(0.05)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            logger.warning(
                "webbrowser.open failed; user must navigate to %s manually", url
            )

    try:
        result = await asyncio.wait_for(done, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        result = VerifyResult(
            status="timeout",
            detail=(
                f"User did not complete verification within "
                f"{timeout_seconds:.0f}s."
            ),
        )
    finally:
        # Give the page a moment to render the success/decline state before
        # we yank the server.
        await asyncio.sleep(0.3)
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except asyncio.TimeoutError:
            server_task.cancel()

    result.url = url
    return result
