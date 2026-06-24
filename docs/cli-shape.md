# fourok CLI shape draft

Purpose: make the CLI feel like a small product surface, not an internal toolbox.

This is a draft for discussion. The goal is to agree on the command shape before moving code.

## Product principle

A new user should learn the CLI in one minute:

```bash
fourok onboard
fourok status
fourok retrieve "What do we know about the renewal?"
```

Everything else is either an admin task or a developer/operator task.

## Proposed top-level commands

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
- produce a human-readable answer block by default
- optionally produce stable JSON for agents/tools

Possible aliases, if wanted later:

- `fourok ask` as a friendlier interactive wrapper
- `fourok search` only if we need a low-level power-user command

Default stance: keep only `retrieve` public until proven otherwise.

### 2. `fourok status`

Daily user/client readiness command.

Use when someone asks: “Is fourok ready to answer questions?”

Example:

```bash
fourok status
fourok status --json
```

Responsibilities:

- show whether local/runtime storage is reachable
- show whether retrieval data exists
- show connector/import freshness at a high level
- show whether permissions/audit basics are active
- give the next useful action, not a wall of diagnostics

Example output shape:

```text
fourok is ready

Context:      1,284 source records, 3,942 retrieval units
Freshness:    Slack 12m ago, Linear 34m ago, Drive not connected
Permissions:  enabled
Audit:        enabled

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
- start or verify the local stack
- seed safe demo/fixture data when requested
- run `fourok status`
- run one demo `fourok retrieve` query
- never ask for or write secrets by default

Important boundary:

- onboarding can tell the user how to add real connectors later
- onboarding should not become connector auth, secret management, or deployment ops

Possible flow:

```text
1. Check prerequisites
2. Install/sync local dependencies if needed
3. Start local stack
4. Seed demo data
5. Verify status
6. Show first retrieve command
```

## Where the rest should go

### `fourok admin ...`

Administrative/operator tasks.

This is for people maintaining the deployment, not casual users.

Candidates to move under `fourok admin`:

- imports and ingestion
- connector checkpoint/job inspection
- webhook queue/process commands
- audit and retention commands
- backup and restore commands
- runtime monitor
- operator dashboard/status internals
- acceptance/readiness/proof checks

Examples:

```bash
fourok admin imports run
fourok admin connectors status
fourok admin audit summary
fourok admin backup postgres
fourok admin retention status
fourok admin runtime monitor
```

Question: should this be `fourok admin ...` or a separate `fourok-admin` binary?

Default recommendation: `fourok admin ...` so there is still one binary, but the public help stays grouped and readable.

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

Default recommendation: keep `fourok-dev` as-is, but prune any client-facing wording from it.

## Proposed public help screen

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

If we want an even stricter client-facing view, hide `admin` from the top help and document it separately.

## Migration from current CLI

Current visible commands should be mapped, not deleted blindly.

| Current area | New home |
| --- | --- |
| `retrieve` | `fourok retrieve` |
| `search`, `search-state`, `ask` | hide, fold into `retrieve`, or move to `fourok admin debug ...` |
| `health`, `operator-status` | `fourok status` internals |
| `stage1-acceptance`, `acceptance-proof`, `internal-prod-readiness` | `fourok admin proof ...` or `fourok-dev` |
| import/connectors commands | `fourok admin imports ...` / `fourok admin connectors ...` |
| audit/retention/backup | `fourok admin audit ...`, `retention ...`, `backup ...` |
| webhooks | `fourok admin webhooks ...` |
| runtime monitor/services | `fourok admin runtime ...` |
| `eval-retrieval` | `fourok-dev` or `fourok admin eval ...` |

## Open questions

1. Should the product command be only `retrieve`, or do we also want `ask` as an interactive friendly mode?
2. Should `admin` appear in `fourok --help`, or be hidden but available?
3. Should onboarding live in `fourok onboard`, or stay as `install.sh` plus `fourok status`?
4. Should connector setup eventually be `fourok onboard connectors`, or is that clearly admin?
5. Do we want `fourok status` to be safe for non-technical client users, or mostly operator-readable?

## Suggested first implementation slice

Do not move everything at once.

1. Add `fourok status` as the friendly wrapper around current health/operator checks.
2. Add `fourok onboard --check` as a no-side-effect guided check.
3. Keep `fourok retrieve` as the main retrieval command.
4. Move current long-tail commands behind `fourok admin` or hide them from top-level help.
5. Update README to show only:

```bash
curl -fsSL https://raw.githubusercontent.com/project-fourok/fourok/main/install.sh | bash
fourok onboard
fourok status
fourok retrieve "What changed this week?"
```
