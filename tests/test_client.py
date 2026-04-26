"""HTTP client tests against an in-process httpx mock transport."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from engram_mcp_sdk.client import (
    EngramClient,
    EngramServerError,
    UnauthorizedError,
)


def _client_with_handler(handler):
    transport = httpx.MockTransport(handler)
    return EngramClient(
        server_url="http://test", timeout_seconds=2.0, transport=transport
    )


async def test_fetch_idkit_config_round_trips() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "app_id": "app_xxx",
                "action": "get-access-token",
                "rp_context": {
                    "rp_id": "rp_yyy",
                    "nonce": "0xabc",
                    "created_at": 1,
                    "expires_at": 2,
                    "signature": "0xdef",
                },
            },
        )

    client = _client_with_handler(handler)
    cfg = await client.fetch_idkit_config()
    assert cfg.app_id == "app_xxx"
    assert cfg.action == "get-access-token"
    assert cfg.rp_context["rp_id"] == "rp_yyy"
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/world-id/idkit-config")


async def test_exchange_proof_for_token_returns_token() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"access_token": "tok-123"})

    client = _client_with_handler(handler)
    token = await client.exchange_proof_for_token({"protocol_version": "3.0"})
    assert token == "tok-123"
    assert seen["url"].endswith("/world-id/access-token")
    assert b"protocol_version" in seen["body"]


async def test_learn_posts_to_org_path_with_stacked_headers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["world_id"] = request.headers.get("x-world-id-token")
        captured["body"] = request.content
        return httpx.Response(200, json={"id": "mem-1"})

    client = _client_with_handler(handler)
    out = await client.learn(
        api_key="key-abc",
        access_token="tok-xyz",
        content="hello",
    )
    assert out == {"id": "mem-1"}
    # No org id in the path -- engram-server resolves it from the API key.
    assert captured["url"].endswith("/v1/organizations/learn")
    assert captured["auth"] == "Bearer key-abc"
    assert captured["world_id"] == "tok-xyz"
    assert b"hello" in captured["body"]


async def test_recall_posts_to_org_path_with_stacked_headers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["world_id"] = request.headers.get("x-world-id-token")
        captured["body"] = request.content
        return httpx.Response(200, json={"results": []})

    client = _client_with_handler(handler)
    out = await client.recall(
        api_key="key-abc",
        access_token="tok",
        query="foo",
        limit=3,
    )
    assert out == {"results": []}
    assert captured["url"].endswith("/v1/organizations/recall")
    assert captured["auth"] == "Bearer key-abc"
    assert captured["world_id"] == "tok"
    body = captured["body"].decode()
    assert "foo" in body and "3" in body


async def test_401_raises_unauthorized() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "expired"})

    client = _client_with_handler(handler)
    with pytest.raises(UnauthorizedError) as excinfo:
        await client.learn(api_key="k", access_token="tok", content="x")
    assert excinfo.value.status_code == 401
    assert excinfo.value.body == {"detail": "expired"}


async def test_500_raises_engram_server_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client_with_handler(handler)
    with pytest.raises(EngramServerError) as excinfo:
        await client.recall(api_key="k", access_token="tok", query="q")
    assert excinfo.value.status_code == 500
    assert excinfo.value.body == "boom"
