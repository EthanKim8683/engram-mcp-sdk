"""Round-trip the on-disk state file."""

from __future__ import annotations

from pathlib import Path

from engram_mcp_sdk.state import (
    State,
    clear_state,
    load_state,
    record_decline,
    record_token,
    save_state,
)


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path / "nope.json") == State()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, State(access_token="tok-123"))
    assert load_state(path) == State(access_token="tok-123")


def test_record_token_clears_decline(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    record_decline(path)
    assert load_state(path).has_declined
    record_token(path, "tok-abc")
    after = load_state(path)
    assert after.is_verified
    assert not after.has_declined


def test_record_decline_preserves_existing_token(tmp_path: Path) -> None:
    """If the user already has a token, declining shouldn't yank it."""

    path = tmp_path / "state.json"
    record_token(path, "tok-1")
    record_decline(path)
    after = load_state(path)
    assert after.access_token == "tok-1"
    # has_declined is False because is_verified short-circuits it
    assert after.is_verified
    assert not after.has_declined


def test_clear_state_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clear_state(path)  # missing file should not raise
    record_token(path, "tok-1")
    clear_state(path)
    assert not path.exists()


def test_corrupt_state_loads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not-json{")
    assert load_state(path) == State()


def test_state_file_mode_is_user_only(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, State(access_token="tok-secure"))
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
