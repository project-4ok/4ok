# fourok CLI shape

Purpose: make the CLI feel like a small product surface, not an internal toolbox.

This document captures the agreed command shape.

## Product principle

A new user should learn the CLI in one minute:

```bash
fourok onboard
fourok status
fourok retrieve "What do we know about the renewal?"
```

Everything else is either an admin task or a developer/operator task.

## Top-level commands

### 1. `fourok retrieve`

Daily user/client command.

Use when a human or agent needs source-backed company context.

Example:

```bash
fourok retrieve "What happened with the Acme renewal?"
fourok retrieve "Summarize the latest customer risks" --json
```

Responsibilities:

- search governed company context
- apply permissions/lifecycle filters
- return source-backed evidence
- produce a human-readable answer/evidence block by default
- optionally produce stable JSON for agents/tools

Decision: use `retrieve`, not `ask`, as the product command. `ask`, `search`, and `search-state` are internal/admin/debug surfaces unless later proven necessary for clients.

### 2. `fourok status`

Daily user/client readiness command.

Use when someone asks: “Is fourok ready to answer questions?”

Example:

```bash
fourok status
fourok status --json
```

Responsibilities:

- show whether fourok is ready in non-technical language
- show whether local/runtime storage is reachable
- show whether retrieval data exists
- show connector/import freshness only at a high level
- give the next useful action, not a wall of diagnostics

Boundary: `status` must be safe for non-technical client users. Detailed runtime, connector, freshness, logs, and database diagnostics belong under `fourok admin ...` or `fourok-dev ...`.

Example output shape:

```text
fourok is ready

Context: 1,284 source records, 3,942 retrieval units

Try:
  fourok retrieve "What changed this week?"
```

### 3. `fourok onboard`

Guided setup/onboarding command.

Use when someone is new or wants to repair a local setup.

Example:

```bash
fourok onboard
fourok onboard --check
fourok onboard --demo
```

Responsibilities:

- explain prerequisites in plain language
- check Docker, uv, Python, and repo/runtime files
- start or verify the local stack when appropriate
- seed safe demo/fixture data when requested
- run or suggest `fourok status`
- run or suggest one demo `fourok retrieve` query
- never ask for or write secrets by default

Connector setup decision: connector onboarding should live inside `fourok onboard`. It may guide the user, but should not silently collect or store secrets.

Installer decision: `install.sh` stays as the one-command bootstrap, but should end by telling the user to run `fourok onboard` next.

### 4. `fourok admin ...`

Administrative/operator tasks.

This appears in `fourok --help`, but is clearly separated from daily client commands.

Candidates under `fourok admin`:

- imports and ingestion
- connector checkpoint/job inspection
- webhook queue/process commands
- audit and retention commands
- backup and restore commands
- runtime monitor
- operator dashboard/status internals
- acceptance/readiness/proof checks
- low-level search/debug/eval commands

Examples:

```bash
fourok admin connector-jobs
fourok admin connector-checkpoint slack
fourok admin audit-summary
fourok admin postgres-backup
fourok admin retention-status
fourok admin runtime-monitor
```

Decision: use `fourok admin ...`, not a separate `fourok-admin` binary, so there is still one product entrypoint.

## Developer command

### `fourok-dev ...`

Developer-only project tooling.

Keep this separate from the product CLI.

Examples that belong here:

- format
- lint
- test
- check
- compose-config
- stack-up
- pipeline-ps
- logs-status
- dagster-status
- install-hooks
- agent-diagnostics

## Public help screen

```text
usage: fourok COMMAND ...

Governed company context retrieval for AI agents.

Commands:
  retrieve   Retrieve source-backed company context.
  status     Show whether fourok is ready to retrieve context.
  onboard    Set up or verify a local fourok environment.
  admin      Administrative commands for operators.

Run `fourok COMMAND --help` for details.
```

## Migration from current CLI

Current visible commands should be mapped, not deleted blindly.

| Current area | New home |
| --- | --- |
| `retrieve` | `fourok retrieve` |
| `search`, `search-state`, `ask` | hidden compatibility or `fourok admin ...` |
| `health`, `operator-status` | `fourok status` internals / `fourok admin health` |
| `stage1-acceptance`, `acceptance-proof`, `internal-prod-readiness` | `fourok admin ...` or `fourok-dev` |
| import/connectors commands | `fourok admin ...`; guided setup starts at `fourok onboard` |
| audit/retention/backup | `fourok admin ...` |
| webhooks | `fourok admin ...` |
| runtime monitor/services | `fourok admin ...` |
| `eval-retrieval` | `fourok-dev` or `fourok admin ...` |

## Implementation slices

1. Make `fourok --help` show only `retrieve`, `status`, `onboard`, and `admin`.
2. Keep old top-level commands as hidden compatibility while moving docs/examples to `fourok admin ...`.
3. Add `fourok status` as the friendly wrapper around current health/operator checks.
4. Add `fourok onboard` as the safe guidance command.
5. Update `install.sh` and README to point users to:

```bash
curl -fsSL https://raw.githubusercontent.com/project-fourok/fourok/main/install.sh | bash
fourok onboard
fourok status
fourok retrieve "What changed this week?"
```
