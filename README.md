# Engram MCP SDK

A drop-in [FastMCP][fastmcp] sub-server that augments any MCP server with
Engram's memory tools, gated behind a one-time World ID verification.

[fastmcp]: https://gofastmcp.com/

The SDK exposes three tools:

| Tool              | What it does                                                                |
| ----------------- | --------------------------------------------------------------------------- |
| `learn`           | Stores a fact in the user's Engram memory.                                  |
| `recall`          | Searches the user's Engram memory for facts matching a query.               |
| `verify_world_id` | Walks the user through a one-time World ID verification (browser flow).     |

`learn` and `recall` refuse to run until the user has verified — when called
in an unverified state they return a `ToolError` whose message tells the
agent to call `verify_world_id`. If the user explicitly declines (clicks
"I'd rather not" on the verification page), the SDK persists that
preference and the memory tools continue to refuse with a "user declined"
message until the user asks the agent to re-verify.

## Install

```bash
uv add engram-mcp-sdk
# or:  pip install engram-mcp-sdk
```

## Usage

### As a sub-server mounted into an existing MCP

```python
from fastmcp import FastMCP
from engram_mcp_sdk import engram

mcp = FastMCP("my-app")
mcp.mount(engram, namespace="engram")

if __name__ == "__main__":
    mcp.run()
```

The mounted tools become `engram_learn`, `engram_recall`, and
`engram_verify_world_id` (use a different `namespace` if you prefer
something else, or pass `namespace=""` to mount un-prefixed).

### As a standalone stdio server

```bash
python -m engram_mcp_sdk
```

This is the right shape if Engram is the only MCP surface you want to
expose to the host (e.g. Claude Desktop).

## Configuration

| Env var                        | Default                              | Notes                                                                |
| ------------------------------ | ------------------------------------ | -------------------------------------------------------------------- |
| `ENGRAM_SERVER_URL`            | `http://localhost:8000`              | Base URL of engram-server (no trailing slash).                       |
| `ENGRAM_STATE_DIR`             | `<platform user config dir>`         | Where the cached access token + opt-out marker live.                 |
| `ENGRAM_VERIFY_TIMEOUT_SECONDS`| `300`                                | How long `verify_world_id` waits for the user to complete the page.  |
| `ENGRAM_HTTP_TIMEOUT_SECONDS`  | `20`                                 | Per-request timeout against engram-server.                           |

## How verification works

`verify_world_id`:

1. Picks a random free port on `127.0.0.1` and binds a tiny [Starlette][s]
   app behind [uvicorn][u].
2. Opens the user's default browser at `http://127.0.0.1:<port>/`. (On
   headless boxes the URL is logged so the user can open it manually.)
3. The page loads `@worldcoin/idkit-core` from a CDN, fetches a signed
   `rp_context` from engram-server (proxied through the local server),
   and presents the user with two buttons:
   - **Verify with World ID** — runs `IDKit.request(...)`, polls until
     World App returns a proof, then POSTs the proof to the local
     `/proof` endpoint, which forwards it to engram-server's
     `/world-id/access-token` route. The resulting bearer token is
     persisted to the SDK state file.
   - **I'd rather not** — POSTs to `/decline`, which records the
     opt-out in the state file. Memory tools then refuse with a clear
     "user declined" message.
4. The local server shuts down once either branch resolves, or after
   `ENGRAM_VERIFY_TIMEOUT_SECONDS`.

[s]: https://www.starlette.io/
[u]: https://www.uvicorn.org/

## State file

Lives at `<state_dir>/state.json` (mode `0600`). Two fields:

```json
{
  "access_token": "..." ,
  "declined_at":  "2026-04-26T08:31:42+00:00"
}
```

Either field may be `null`. Clearing this file (or just deleting it) is the
"factory reset" — the next memory-tool call will prompt the user to
re-verify.

## Engram-server contract

The SDK assumes engram-server exposes two HTTP routes (added separately as
a follow-up to engram-server PR #5):

```
GET  /world-id/idkit-config
  -> 200 {
       "app_id":     "app_xxxx",
       "action":     "get-access-token",
       "rp_context": {
         "rp_id":      "rp_xxxx",
         "nonce":      "0x...",
         "created_at": 1700000000,
         "expires_at": 1700000300,
         "signature":  "0x..."
       }
     }

POST /world-id/access-token
  body: { "proof": <IDKit verify body> }
  -> 200 { "access_token": "<opaque bearer credential>" }
  -> 401 if the proof is invalid
```

The memory tools call `POST /v1/learn` and `POST /v1/recall` with
`Authorization: Bearer <access_token>` (the cached token from the state
file).

## Development

```bash
uv sync --extra dev
uv run pytest
```

The end-to-end test in `tests/test_verify.py` actually binds a uvicorn
server on a real localhost port and drives the decline path; it stubs out
`webbrowser.open` so no real browser is launched.
