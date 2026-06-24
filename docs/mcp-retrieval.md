# fourok MCP Retrieval Server

fourok exposes a local stdio MCP server for agents and a Docker-started
streamable HTTP MCP server for clients that connect over HTTP. Both paths wrap
the retrieval API boundary in `fourok.retrieval.api.RetrievalAPI`.

## Tools

- `search_fourok`: searches governed retrieval units with permission filtering and
  returns `query`, `results`, `summary`, `result_candidates`, `evidence_items`,
  object/entity fields, `limitations`, and `audit_ref`.
- `operator_status`: returns the same compact runtime operator status as
  `fourok operator-status`, including active imported-item counts, retrieval
  record totals/status counts, connector job freshness, and latest live
  ingestion metadata.

Both tools accept optional `state`, `database_url`, and `config` arguments. If
`database_url` is omitted and `state` is not provided, the server uses
`FOUROK_DATABASE_URL`; otherwise it falls back to the explicit or default SQLite
state path. `config` points at the normal fourok runtime TOML file and applies the
configured raw-store and retrieval settings.

## Run

Stdio mode for local agent clients:

```bash
uv run fourok-mcp
```

Streamable HTTP mode for HTTP MCP clients:

```bash
uv run fourok-mcp --transport streamable-http --host 0.0.0.0 --port 8010 --mount-path /mcp
```

Docker Compose starts the HTTP MCP server by default alongside Postgres and the
runtime app:

```bash
docker compose up -d --build
```

Default local endpoint:

```text
http://127.0.0.1:8010/mcp
```

Override the host port with `FOUROK_MCP_PORT=...`. The compose service binds to
loopback only by default. If a hosted client such as ChatGPT web needs to reach
it from outside this machine, put an HTTPS tunnel/reverse proxy in front of this
local endpoint and keep database credentials out of the client config.

## Hosted ChatGPT/Claude readiness gaps

The Docker Compose HTTP MCP service is enough for local MCP clients, but it is
not yet a complete setup for web-hosted ChatGPT or Claude clients. Before
exposing this beyond localhost, implement and verify:

- Public HTTPS endpoint: terminate TLS in a maintained reverse proxy or tunnel
  and route only the MCP path, for example `/mcp`, to the local `mcp` service.
- Authentication: require bearer-token or OAuth-style auth at the edge before
  any MCP request reaches the server. The current local endpoint is unauthenticated.
- Secret handling: keep `FOUROK_DATABASE_URL`, runtime config, and connector
  credentials server-side only. Hosted clients should receive only an MCP URL
  and auth material, never database credentials.
- Host allowlist / access policy: decide which hosted clients, users, and
  workspaces may call the MCP endpoint; log denials.
- Rate limits and request limits: cap request size, concurrency, and tool-call
  rate so a hosted client cannot overload retrieval or the runtime database.
- Audit trail: record remote caller identity, tool name, query length, result
  count, and audit ref without logging raw secrets or sensitive query text.
- CORS / protocol compatibility: verify the exact hosted-client MCP transport
  requirements. Keep streamable HTTP compatibility tests for the client version
  being targeted.
- Operator smoke test: add a repeatable check that connects through the public
  HTTPS URL, lists `search_fourok` and `operator_status`, and runs a safe
  `operator_status` call.
- Deployment runbook: document how to rotate tokens, disable the public endpoint,
  inspect logs, and fall back to loopback-only local mode.

Hermes can connect to the stdio server with this native MCP config shape. Set
`cwd` to the repository checkout that contains this `pyproject.toml`:

```json
{
  "mcpServers": {
    "fourok-retrieval": {
      "command": "uv",
      "args": ["run", "fourok-mcp"],
      "cwd": "/home/simon/Projects/project-fourok/fourok",
      "env": {
        "FOUROK_DATABASE_URL": "postgresql+psycopg://fourok:...@127.0.0.1:5432/fourok",
        "FOUROK_CONFIG_PATH": "/home/simon/Projects/project-fourok/fourok/fourok.toml"
      }
    }
  }
}
```

Do not commit real database credentials in client config. Prefer local
environment injection for secrets.

## Local Verification

Unit-level contract:

```bash
uv run pytest tests/runtime/test_mcp_retrieval.py -q
```

MCP SDK registration check:

```bash
uv run python - <<'PY'
import anyio
from fourok.runtime.mcp_retrieval import build_mcp_server

async def main():
    server = build_mcp_server()
    print([tool.name for tool in await server.list_tools()])

anyio.run(main)
PY
```

Live retrieval comparison, to run against the local runtime database after the
database is available:

```bash
uv run fourok search-state "refund escalation" \
  --database-url "$FOUROK_DATABASE_URL" \
  --role operator \
  --limit 5
```

Interactive MCP inspection, when the local runtime database is available:

```bash
npx -y @modelcontextprotocol/inspector uv run fourok-mcp
```

Expected tools are `search_fourok` and `operator_status`. Use `search_fourok` with the
same query, roles, and optional `config` as the CLI comparison. The MCP tool intentionally
does not expose a caller-facing result limit; it returns an agent-ready evidence pack and
retrieval notes instead of asking clients to tune candidate counts.

SDK stdio smoke check:

```bash
uv run python - <<'PY'
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "fourok-mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])

anyio.run(main)
PY
```
