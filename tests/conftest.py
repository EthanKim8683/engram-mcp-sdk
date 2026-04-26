"""Shared test fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engram_mcp_sdk.config import Config


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def config(state_dir: Path) -> Config:
    return Config(
        server_url="http://test-server:8000",
        state_dir=state_dir,
        verify_timeout_seconds=2.0,
        http_timeout_seconds=2.0,
        api_key="test-api-key",
        org_id="test-org",
    )


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, state_dir: Path) -> None:
    """Make sure tests never read or write the real user config dir."""

    monkeypatch.setenv("ENGRAM_STATE_DIR", str(state_dir))
    monkeypatch.setenv("ENGRAM_SERVER_URL", "http://test-server:8000")
    monkeypatch.setenv("ENGRAM_API_KEY", "test-api-key")
    monkeypatch.setenv("ENGRAM_ORG_ID", "test-org")
    # Disable cwd .env files / etc.
    for var in ("HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(state_dir.parent / "fake-home"))
    os.environ.pop("ENGRAM_VERIFY_TIMEOUT_SECONDS", None)
