"""Runtime configuration for the Engram MCP SDK.

All knobs are read from environment variables on first access so a host
process can override them at startup.

Required env var (server can still start without it, but the ``learn`` /
``recall`` tools will fail at call time with a clear error -- the
``verify_world_id`` tool stays usable so a user can complete the World ID
verification ahead of any memory write):

* ``ENGRAM_API_KEY`` -- the customer-organization's API key. Sent as
  ``Authorization: Bearer <api_key>`` on every memory call. The
  organization id is bound to this key server-side, so the SDK doesn't
  need (and the host doesn't have to configure) a separate ``ORG_ID``.

Other env vars all have defaults and are documented in the README.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

DEFAULT_VERIFY_TIMEOUT_SECONDS = 300.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class Config:
    """Resolved SDK configuration. Build via :func:`load_config`."""

    server_url: str
    state_dir: Path
    verify_timeout_seconds: float
    http_timeout_seconds: float
    api_key: str | None

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"


def _state_dir() -> Path:
    override = os.environ.get("ENGRAM_STATE_DIR")
    if override:
        return Path(override)
    return Path(user_config_dir("engram-mcp-sdk"))


def load_config() -> Config:
    """Read environment variables and return a fresh ``Config``.

    Re-reads on every call so tests can monkeypatch ``os.environ`` between
    cases without import-time pinning.
    """

    server_url = os.environ.get("ENGRAM_SERVER_URL", "http://localhost:8000")
    return Config(
        server_url=server_url.rstrip("/"),
        state_dir=_state_dir(),
        verify_timeout_seconds=float(
            os.environ.get(
                "ENGRAM_VERIFY_TIMEOUT_SECONDS", DEFAULT_VERIFY_TIMEOUT_SECONDS
            )
        ),
        http_timeout_seconds=float(
            os.environ.get(
                "ENGRAM_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS
            )
        ),
        api_key=os.environ.get("ENGRAM_API_KEY") or None,
    )
