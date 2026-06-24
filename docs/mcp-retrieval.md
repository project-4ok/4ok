# 4OK MCP Retrieval Server

4OK exposes a local stdio MCP server for agents that need to test retrieval
against governed state. The server wraps the same `GovernedContext.search_context`
path used by `four-ok search-state`.

## Tools

- `search_4ok`: searches governed retrieval units with permission filtering and
  returns `query`, `results`, `summary`, `result_candidates`, `evidence_items`,
  object/entity fields, `limitations`, and `audit_ref`.
- `operator_status`: returns the same compact runtime operator status as
  `four-ok operator-status`, including active imported-item counts, retrieval
  record totals/status counts, connector job freshness, and latest live
  ingestion metadata.

Both tools accept optional `state`, `database_url`, and `config` arguments. If
`database_url` is omitted and `state` is not provided, the server uses
`FOUR_OK_DATABASE_URL`; otherwise it falls back to the explicit or default SQLite
state path. `config` points at the normal 4OK runtime TOML file and applies the
configured raw-store and retrieval settings.

## Run

```bash
uv run four-ok-mcp
```

Hermes can connect to the stdio server with this native MCP config shape. Set
`cwd` to the repository checkout that contains this `pyproject.toml`:

```json
{
  "mcpServers": {
    "4ok-retrieval": {
      "command": "uv",
      "args": ["run", "four-ok-mcp"],
      "cwd": "/home/simon/Projects/project-4ok/4ok",
      "env": {
        "FOUR_OK_DATABASE_URL": "postgresql+psycopg://4ok:...@127.0.0.1:5432/4ok",
        "FOUR_OK_CONFIG_PATH": "/home/simon/Projects/project-4ok/4ok/4ok.toml"
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
uv run four-ok search-state "refund escalation" \
  --database-url "$FOUR_OK_DATABASE_URL" \
  --role operator \
  --limit 5
```

Interactive MCP inspection, when the local runtime database is available:

```bash
npx -y @modelcontextprotocol/inspector uv run four-ok-mcp
```

Expected tools are `search_4ok` and `operator_status`. Use `search_4ok` with the
same query, `limit`, roles, and optional `config` as the CLI comparison.

SDK stdio smoke check:

```bash
uv run python - <<'PY'
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "four-ok-mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])

anyio.run(main)
PY
```
