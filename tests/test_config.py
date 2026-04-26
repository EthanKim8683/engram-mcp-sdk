"""Tests for the SDK's runtime configuration resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from engram_mcp_sdk.config import (
    DEFAULT_STATE_DIR_NAME,
    default_state_dir,
    load_config,
)


def test_default_state_dir_is_under_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fallback state dir is a fixed ``$HOME/.engram`` path.

    All MCP servers that mount ``engram_mcp_sdk`` and run as the same OS
    user must land on the *same* state file, so a successful World ID
    verification in one MCP host applies to every other one.
    """

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ENGRAM_STATE_DIR", raising=False)

    assert default_state_dir() == fake_home / DEFAULT_STATE_DIR_NAME
    assert load_config().state_dir == fake_home / DEFAULT_STATE_DIR_NAME


def test_engram_state_dir_overrides_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hosts that want isolation can still point at any directory."""

    override = tmp_path / "custom-state"
    monkeypatch.setenv("ENGRAM_STATE_DIR", str(override))
    cfg = load_config()
    assert cfg.state_dir == override
    assert cfg.state_path == override / "state.json"


def test_two_independent_loads_resolve_to_the_same_state_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Simulate two MCP servers in the same user session.

    Each server constructs its own ``Config`` via ``load_config``; both
    must write to (and read from) the same ``state.json`` so verification
    is shared.
    """

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ENGRAM_STATE_DIR", raising=False)

    server_a = load_config()
    server_b = load_config()
    assert server_a.state_path == server_b.state_path
    assert server_a.state_path == fake_home / DEFAULT_STATE_DIR_NAME / "state.json"
