"""Thin HTTP client around engram-server.

Wraps the four engram-server endpoints the SDK depends on:

* ``GET  /world-id/idkit-config``                            -- public IDKit
  init payload (``app_id`` + ``action`` + signed ``rp_context``).
* ``POST /world-id/access-token``                            -- exchange an
  IDKit proof for a bearer access token.
* ``POST /v1/organizations/learn``                           -- store a memory
  in the org's container. Stacked auth: ``Authorization: Bearer <api_key>``
  identifies the *organization* (engram-server resolves the API key to the
  bound ``organization_id`` server-side); ``X-World-ID-Token:
  <access_token>`` proves a uniquely-verified human is making the call.
* ``POST /v1/organizations/recall``                          -- search that
  same container with the same two headers.

The client surfaces typed exceptions so the FastMCP tool layer can decide
whether to translate a 401 into "ask the user to re-verify" vs propagate
network errors as-is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class EngramServerError(RuntimeError):
    """Engram-server returned a non-success response."""

    def __init__(self, message: str, *, status_code: int, body: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class UnauthorizedError(EngramServerError):
    """One of the bearer credentials was missing/expired/revoked.

    Could be the org API key or the World ID access token -- engram-server
    returns 401 in both cases. The tool layer assumes "re-verify" because
    the API key is configured statically on the host so it's the World ID
    token that's most likely stale.
    """


@dataclass(frozen=True)
class IDKitConfig:
    """Everything the localhost IDKit page needs to call ``IDKit.request``."""

    app_id: str
    action: str
    rp_context: dict[str, Any]


class EngramClient:
    """HTTPX-based client. Construct once per request boundary."""

    def __init__(
        self,
        *,
        server_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "base_url": self._server_url,
            "timeout": self._timeout,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def fetch_idkit_config(self) -> IDKitConfig:
        async with self._client() as c:
            resp = await c.get("/world-id/idkit-config")
        _raise_for_status(resp)
        data = resp.json()
        return IDKitConfig(
            app_id=data["app_id"],
            action=data["action"],
            rp_context=data["rp_context"],
        )

    async def exchange_proof_for_token(self, proof: dict[str, Any]) -> str:
        async with self._client() as c:
            resp = await c.post(
                "/world-id/access-token", json={"proof": proof}
            )
        _raise_for_status(resp)
        return resp.json()["access_token"]

    async def learn(
        self,
        *,
        api_key: str,
        access_token: str,
        content: str,
    ) -> dict[str, Any]:
        return await self._org_post(
            "learn",
            api_key=api_key,
            access_token=access_token,
            body={"content": content},
        )

    async def recall(
        self,
        *,
        api_key: str,
        access_token: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        return await self._org_post(
            "recall",
            api_key=api_key,
            access_token=access_token,
            body={"query": query, "limit": limit},
        )

    async def _org_post(
        self,
        verb: str,
        *,
        api_key: str,
        access_token: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._client() as c:
            resp = await c.post(
                f"/v1/organizations/{verb}",
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-World-ID-Token": access_token,
                },
            )
        _raise_for_status(resp)
        return resp.json()


def _raise_for_status(resp: httpx.Response) -> None:
    if 200 <= resp.status_code < 300:
        return
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text
    if resp.status_code == 401:
        raise UnauthorizedError(
            "engram-server rejected the request credentials",
            status_code=401,
            body=body,
        )
    raise EngramServerError(
        f"engram-server returned {resp.status_code}",
        status_code=resp.status_code,
        body=body,
    )
