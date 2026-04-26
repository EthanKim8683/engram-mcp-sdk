"""End-to-end FastMCP-tool tests against fake EngramClient + verify flow.

Covers the three behaviours the user asked for:

* Unverified ``learn`` / ``recall`` calls fail with a directive to call
  ``verify_world_id`` (the agent should pick this up and route accordingly).
* Declined preference is persisted across calls and surfaced in error text.
* A successful ``verify_world_id`` clears any prior decline; a declined
  flow records it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp.exceptions import ToolError

from engram_mcp_sdk.client import EngramClient
from engram_mcp_sdk.config import Config
from engram_mcp_sdk.server import build_engram_server
from engram_mcp_sdk.state import (
    load_state,
    record_decline,
    record_token,
)
from engram_mcp_sdk.verify import VerifyResult


class _FakeClient:
    """Minimal stand-in for :class:`EngramClient`."""

    def __init__(self) -> None:
        self.learn_calls: list[dict[str, Any]] = []
        self.recall_calls: list[dict[str, Any]] = []
        self.learn_response: dict[str, Any] = {"id": "mem-1"}
        self.recall_response: dict[str, Any] = {"results": []}
        self.exchange_response: str = "tok-fresh"

    async def learn(
        self,
        *,
        api_key: str,
        access_token: str,
        org_id: str,
        content: str,
    ) -> dict[str, Any]:
        self.learn_calls.append(
            {
                "api_key": api_key,
                "access_token": access_token,
                "org_id": org_id,
                "content": content,
            }
        )
        return self.learn_response

    async def recall(
        self,
        *,
        api_key: str,
        access_token: str,
        org_id: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        self.recall_calls.append(
            {
                "api_key": api_key,
                "access_token": access_token,
                "org_id": org_id,
                "query": query,
                "limit": limit,
            }
        )
        return self.recall_response

    # Unused on this code path -- the verify flow is monkeypatched away below.
    async def fetch_idkit_config(self) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def exchange_proof_for_token(
        self, _proof: dict[str, Any]
    ) -> str:  # pragma: no cover
        return self.exchange_response


def _build(config: Config, fake: _FakeClient):
    return build_engram_server(config=config, client_factory=lambda: fake)


async def _call(server, name: str, args: dict[str, Any]) -> Any:
    """Invoke a FastMCP tool by name and return its raw result payload."""

    return await server._call_tool_mcp(name, args)


# ---------- gating logic ----------------------------------------------------


def _config_without_org(config: Config) -> Config:
    return Config(
        server_url=config.server_url,
        state_dir=config.state_dir,
        verify_timeout_seconds=config.verify_timeout_seconds,
        http_timeout_seconds=config.http_timeout_seconds,
        api_key=None,
        org_id=None,
    )


async def test_learn_fails_when_org_config_missing(config: Config) -> None:
    """Even verified users can't write if the host hasn't set ENGRAM_API_KEY."""
    record_token(config.state_path, "tok-cached")
    server = _build(_config_without_org(config), _FakeClient())
    with pytest.raises(ToolError) as excinfo:
        await _call(server, "learn", {"content": "x"})
    assert "ENGRAM_API_KEY" in str(excinfo.value)
    assert "ENGRAM_ORG_ID" in str(excinfo.value)


async def test_recall_fails_when_org_config_missing(config: Config) -> None:
    record_token(config.state_path, "tok-cached")
    server = _build(_config_without_org(config), _FakeClient())
    with pytest.raises(ToolError) as excinfo:
        await _call(server, "recall", {"query": "x"})
    assert "ENGRAM_API_KEY" in str(excinfo.value)


async def test_learn_fails_when_unverified(config: Config) -> None:
    server = _build(config, _FakeClient())
    with pytest.raises(ToolError) as excinfo:
        await _call(server, "learn", {"content": "hi"})
    msg = str(excinfo.value)
    assert "World ID" in msg
    assert "verify_world_id" in msg


async def test_recall_fails_when_unverified(config: Config) -> None:
    server = _build(config, _FakeClient())
    with pytest.raises(ToolError):
        await _call(server, "recall", {"query": "hi"})


async def test_learn_fails_when_declined(config: Config) -> None:
    record_decline(config.state_path)
    server = _build(config, _FakeClient())
    with pytest.raises(ToolError) as excinfo:
        await _call(server, "learn", {"content": "hi"})
    assert "declined" in str(excinfo.value).lower()
    assert "verify_world_id" in str(excinfo.value)


async def test_learn_and_recall_succeed_when_verified(config: Config) -> None:
    record_token(config.state_path, "tok-cached")
    fake = _FakeClient()
    server = _build(config, fake)

    learn_result = await _call(server, "learn", {"content": "the sky is blue"})
    recall_result = await _call(server, "recall", {"query": "color of sky"})

    # FastMCP wraps async tool returns in a CallToolResult; the structured
    # content should round-trip our dicts.
    assert fake.learn_calls == [
        {
            "api_key": "test-api-key",
            "access_token": "tok-cached",
            "org_id": "test-org",
            "content": "the sky is blue",
        }
    ]
    assert fake.recall_calls == [
        {
            "api_key": "test-api-key",
            "access_token": "tok-cached",
            "org_id": "test-org",
            "query": "color of sky",
            "limit": 5,
        }
    ]
    # Sanity: both tool results carry our payloads
    assert "mem-1" in str(learn_result)
    assert "results" in str(recall_result)


# ---------- verify flow ----------------------------------------------------


async def test_verify_world_id_records_token_on_success(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_localhost_verify_flow(*, client, timeout_seconds, **_kw):
        return VerifyResult(
            status="verified",
            detail="ok",
            access_token="tok-from-flow",
        )

    monkeypatch.setattr(
        "engram_mcp_sdk.server.run_localhost_verify_flow",
        fake_run_localhost_verify_flow,
    )

    server = _build(config, _FakeClient())
    out = await _call(server, "verify_world_id", {})

    state = load_state(config.state_path)
    assert state.is_verified
    assert state.access_token == "tok-from-flow"
    assert "verified" in str(out).lower()


async def test_verify_world_id_records_decline(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_localhost_verify_flow(*, client, timeout_seconds, **_kw):
        return VerifyResult(status="declined", detail="user clicked decline")

    monkeypatch.setattr(
        "engram_mcp_sdk.server.run_localhost_verify_flow",
        fake_run_localhost_verify_flow,
    )

    server = _build(config, _FakeClient())
    out = await _call(server, "verify_world_id", {})

    state = load_state(config.state_path)
    assert not state.is_verified
    assert state.has_declined
    assert "declined" in str(out).lower()


async def test_verify_world_id_after_decline_can_succeed(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User initially declines, then changes their mind and re-verifies."""

    record_decline(config.state_path)
    assert load_state(config.state_path).has_declined

    async def fake_run_localhost_verify_flow(*, client, timeout_seconds, **_kw):
        return VerifyResult(
            status="verified", detail="ok", access_token="tok-second-try"
        )

    monkeypatch.setattr(
        "engram_mcp_sdk.server.run_localhost_verify_flow",
        fake_run_localhost_verify_flow,
    )

    server = _build(config, _FakeClient())
    await _call(server, "verify_world_id", {})

    state = load_state(config.state_path)
    assert state.is_verified
    assert not state.has_declined  # is_verified short-circuits has_declined
    assert state.access_token == "tok-second-try"


async def test_unauthorized_response_clears_token_and_directs_to_verify(
    config: Config,
) -> None:
    """If engram-server 401s, the cached token is wiped so the next call
    re-prompts for verification."""

    record_token(config.state_path, "tok-stale")

    class _Unauthorized(_FakeClient):
        async def learn(self, **_kw: Any):
            from engram_mcp_sdk.client import UnauthorizedError

            raise UnauthorizedError(
                "rejected", status_code=401, body={"detail": "bad"}
            )

    server = _build(config, _Unauthorized())
    with pytest.raises(ToolError) as excinfo:
        await _call(server, "learn", {"content": "x"})
    assert "verify_world_id" in str(excinfo.value)
    # state file should be gone -- next call is back to the unverified state
    assert not config.state_path.exists()
