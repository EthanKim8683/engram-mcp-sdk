"""On-disk state for the Engram MCP SDK.

Persists exactly two pieces of information across MCP sessions:

* the World ID access token (an opaque bearer credential the server hands
  back after a successful proof exchange), and
* a "user declined to verify" flag so the memory tools can short-circuit
  with a useful message instead of silently failing every time the agent
  calls them.

Both live in a single JSON file at ``<state_dir>/state.json`` with mode
``0600``. The file is read on every access (small, infrequent) so the
process never holds a stale view if another MCP host instance updates it.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class State:
    """Persisted SDK state. All fields default to ``None``."""

    access_token: str | None = None
    declined_at: str | None = None  # ISO-8601 UTC timestamp

    @property
    def is_verified(self) -> bool:
        return bool(self.access_token)

    @property
    def has_declined(self) -> bool:
        return bool(self.declined_at) and not self.is_verified


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load_state(path: Path) -> State:
    """Read state from disk. Missing or unreadable file -> empty ``State``."""

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return State()
    except OSError:
        return State()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return State()
    if not isinstance(data, dict):
        return State()
    return State(
        access_token=data.get("access_token") or None,
        declined_at=data.get("declined_at") or None,
    )


def save_state(path: Path, state: State) -> None:
    _atomic_write_json(path, asdict(state))


def record_token(path: Path, access_token: str) -> State:
    """Persist a freshly issued access token. Clears any decline flag."""

    state = State(access_token=access_token, declined_at=None)
    save_state(path, state)
    return state


def record_decline(path: Path) -> State:
    """Persist a 'user declined verification' marker."""

    existing = load_state(path)
    state = State(
        access_token=existing.access_token,  # preserve token if somehow set
        declined_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    save_state(path, state)
    return state


def clear_state(path: Path) -> None:
    """Wipe state from disk. Used when the server rejects the cached token."""

    try:
        path.unlink()
    except FileNotFoundError:
        pass
