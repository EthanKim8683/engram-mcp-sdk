# Engram MCP SDK

A drop-in [FastMCP][fastmcp] sub-server that augments any MCP server with
Engram's memory tools. Designed for organizations integrating Engram into
their own product: every memory write requires **both** the organization's
API key (proving the org is a paying customer) **and** a one-time World ID
verification per end-user (proving a uniquely-verified human is making the
call, so a bot army with a leaked API key can't poison memory at scale).

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

They also refuse if the host process hasn't configured `ENGRAM_API_KEY` and
`ENGRAM_ORG_ID` (the org credentials), with a `ToolError` that names both
variables explicitly.

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

| Env var                        | Required                  | Default                              | Notes                                                                |
| ------------------------------ | ------------------------- | ------------------------------------ | -------------------------------------------------------------------- |
| `ENGRAM_API_KEY`               | yes (for `learn`/`recall`)| —                                    | The customer-organization's API key. Sent as `Authorization: Bearer <api_key>` on every memory call. |
| `ENGRAM_ORG_ID`                | yes (for `learn`/`recall`)| —                                    | Organization id those memories belong to. Becomes the path's `{organization_id}` segment. |
| `ENGRAM_SERVER_URL`            | no                        | `http://localhost:8000`              | Base URL of engram-server (no trailing slash).                       |
| `ENGRAM_STATE_DIR`             | no                        | `<platform user config dir>`         | Where the cached access token + opt-out marker live.                 |
| `ENGRAM_VERIFY_TIMEOUT_SECONDS`| no                        | `300`                                | How long `verify_world_id` waits for the user to complete the page.  |
| `ENGRAM_HTTP_TIMEOUT_SECONDS`  | no                        | `20`                                 | Per-request timeout against engram-server.                           |

`ENGRAM_API_KEY` and `ENGRAM_ORG_ID` aren't required at SDK import time —
the `verify_world_id` tool stays usable without them — but `learn` and
`recall` will fail at call time with a clear error if either is missing.

## How auth stacks

```
            +-----------------------------+
  learn /   |  Authorization: Bearer <api_key>     <-- ENGRAM_API_KEY
  recall  --+                                          (per organization,
            |  X-World-ID-Token: <access_token>          static, in env)
            +-----------------------------+
                                            <-- access_token from
                                                verify_world_id
                                                (per human, persisted
                                                 in state.json)
```

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

The SDK targets the **organization slice** of [engram-server][es] (with
World-ID stacked on top). Engram-server also exposes a per-user Supabase-JWT
surface for unauthenticated public search; this SDK doesn't touch it.

[es]: https://github.com/EthanKim8683/engram-server

```
GET  /world-id/idkit-config
  -> 200 {
       "app_id":     "app_xxxx",          # WORLD_ID_APP_ID upstream
       "action":     "get-access-token",  # WORLD_ID_ACTION upstream
       "rp_context": {
         "rp_id":      "rp_xxxx",          # WORLD_ID_RP_ID upstream
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
  -> 502 if the upstream verify request fails

POST /v1/organizations/{org_id}/learn
  headers: {
    "Authorization":   "Bearer <api_key>",      # ENGRAM_API_KEY
    "X-World-ID-Token": "<access_token>"        # from verify_world_id
  }
  body:    { "content": "...", "metadata": {...}? }
  -> 200 <Supermemory documents.add response>
  -> 401 if either credential is missing/invalid
  -> 403 if the API key isn't bound to {org_id} or the verified human is banned

POST /v1/organizations/{org_id}/recall
  headers: same two as /learn
  body:    { "query": "...", "limit": 5?, "similarity_threshold": 0.7? }
  -> 200 <Supermemory search.memories response>
  -> 401 / 403: same as above
```

Required env vars on the engram-server side:
`WORLD_ID_APP_ID`, `WORLD_ID_RP_ID`, `WORLD_ID_ACTION`,
`WORLD_ID_KEY_MASTER_SECRET`, `WORLD_ID_RP_SIGNING_KEY` —
see [engram-server's README][esr] for the full list and defaults.

[esr]: https://github.com/EthanKim8683/engram-server#readme

## Development

```bash
uv sync --extra dev
uv run pytest
```

The end-to-end test in `tests/test_verify.py` actually binds a uvicorn
server on a real localhost port and drives the decline path; it stubs out
`webbrowser.open` so no real browser is launched.
