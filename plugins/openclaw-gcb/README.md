# 4ok OpenClaw Plugin

Local OpenClaw plugin for querying 4ok from an agent.

Tools:

- `gcb_search_context`: runs the local governed search contract and returns the
  evidence pack in tool details.
- `gcb_health`: checks the local runtime database and raw-store boundary.

The plugin is intentionally local-first. By default it runs `gcb` from `PATH`
against `.local/context.sqlite`; set `command = "uv"` and
`commandArgs = ["run", "gcb"]` when using the repository checkout directly.

Equivalent GCB commands:

```bash
uv run gcb search-state "customer renewal" --state .local/context.sqlite
uv run gcb health --state .local/context.sqlite --raw-store .local/raw
```

Security boundary:

- does not expose reveal
- does not inject context into prompts
- does not read from `.reference`
- returns governed search output through the existing GCB CLI/API contract

Build:

```bash
npm install
npm run build
```
