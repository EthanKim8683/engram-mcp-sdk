"""Localhost-flow tests.

Drives the Starlette app directly (no real browser, no real port binding)
to verify the four routes behave correctly. The end-to-end uvicorn dance is
tested in a separate slow test.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from engram_mcp_sdk.client import EngramClient, EngramServerError
from engram_mcp_sdk.verify import (
    VerifyResult,
    build_verify_app,
    run_localhost_verify_flow,
)
from engram_mcp_sdk.verify_page import VERIFY_HTML


async def _asgi_client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def test_index_returns_verify_html() -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()
    client = EngramClient(server_url="http://upstream", timeout_seconds=1.0)
    app = build_verify_app(client=client, on_done=done)

    async with await _asgi_client(app) as http:
        resp = await http.get("/")
    assert resp.status_code == 200
    assert resp.text == VERIFY_HTML
    # Buttons retain their copy across the design refresh.
    assert "Verify with World ID" in resp.text
    assert "I'd rather not" in resp.text
    # Design-guidelines elements: branded title, QR container, deep-link
    # button, IDKit core import, qrcode renderer.
    assert "Connect your World ID" in resp.text
    assert 'id="qr"' in resp.text
    assert "Open in World App" in resp.text
    assert "@worldcoin/idkit-core@4" in resp.text
    assert "qrcode@" in resp.text
    # The page wires its own URL into return_to so mobile users come back.
    assert "return_to: window.location.href" in resp.text


async def test_idkit_config_proxies_upstream() -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()

    upstream_payload = {
        "app_id": "app_xxx",
        "action": "get-access-token",
        "rp_context": {
            "rp_id": "rp_yyy",
            "nonce": "0xabc",
            "created_at": 1,
            "expires_at": 2,
            "signature": "0xdef",
        },
    }

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/world-id/idkit-config"
        return httpx.Response(200, json=upstream_payload)

    client = EngramClient(
        server_url="http://upstream",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(upstream_handler),
    )
    app = build_verify_app(client=client, on_done=done)
    async with await _asgi_client(app) as http:
        resp = await http.get("/idkit-config")
    assert resp.status_code == 200
    assert resp.json() == upstream_payload


async def test_idkit_config_returns_502_on_upstream_failure() -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()

    def upstream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    client = EngramClient(
        server_url="http://upstream",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(upstream_handler),
    )
    app = build_verify_app(client=client, on_done=done)
    async with await _asgi_client(app) as http:
        resp = await http.get("/idkit-config")
    assert resp.status_code == 502


async def test_proof_post_resolves_done_with_verified() -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()

    def upstream_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/world-id/access-token"
        return httpx.Response(200, json={"access_token": "tok-final"})

    client = EngramClient(
        server_url="http://upstream",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(upstream_handler),
    )
    app = build_verify_app(client=client, on_done=done)

    async with await _asgi_client(app) as http:
        resp = await http.post("/proof", json={"protocol_version": "3.0"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "verified"}

    result = await asyncio.wait_for(done, timeout=1.0)
    assert result.status == "verified"
    assert result.access_token == "tok-final"


async def test_proof_post_propagates_upstream_failure_without_resolving() -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()

    def upstream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad proof"})

    client = EngramClient(
        server_url="http://upstream",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(upstream_handler),
    )
    app = build_verify_app(client=client, on_done=done)

    async with await _asgi_client(app) as http:
        resp = await http.post("/proof", json={"protocol_version": "3.0"})
    assert resp.status_code == 401
    # The page can retry, so the future must NOT be resolved on a bad proof.
    assert not done.done()


async def test_decline_post_resolves_done_with_declined() -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[VerifyResult] = loop.create_future()
    client = EngramClient(server_url="http://upstream", timeout_seconds=1.0)
    app = build_verify_app(client=client, on_done=done)

    async with await _asgi_client(app) as http:
        resp = await http.post("/decline")
    assert resp.status_code == 200
    assert resp.json() == {"status": "declined"}

    result = await asyncio.wait_for(done, timeout=1.0)
    assert result.status == "declined"
    assert result.access_token is None


async def test_run_localhost_verify_flow_e2e_resolves_via_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spin up a real uvicorn server, hit /decline, expect a 'declined' result.

    Verifies the full plumbing (port allocation, lifespan, teardown) without
    needing a real browser. We pin the port up front so we can launch a
    driver task before the flow begins.
    """

    from engram_mcp_sdk.verify import _free_port

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"

    captured: list[str] = []
    monkeypatch.setattr(
        "webbrowser.open", lambda u: captured.append(u) or True
    )

    upstream_handler = lambda _request: httpx.Response(  # noqa: E731
        500, text="should not be hit"
    )
    client = EngramClient(
        server_url="http://upstream",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(upstream_handler),
    )

    async def driver() -> None:
        async with httpx.AsyncClient(timeout=2.0) as http:
            for _ in range(100):
                try:
                    r = await http.post(url + "decline")
                    if r.status_code == 200:
                        return
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.05)
            raise RuntimeError("uvicorn never came up")

    driver_task = asyncio.create_task(driver())

    try:
        result = await run_localhost_verify_flow(
            client=client,
            timeout_seconds=10.0,
            open_browser=True,
            port=port,
        )
    finally:
        await driver_task

    assert result.status == "declined"
    assert result.url == url
    assert captured == [url]
