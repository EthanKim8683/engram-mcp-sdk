"""Standalone stdio entry point: ``python -m engram_mcp_sdk``."""

from __future__ import annotations

from engram_mcp_sdk.server import engram


def main() -> None:
    engram.run()


if __name__ == "__main__":
    main()
