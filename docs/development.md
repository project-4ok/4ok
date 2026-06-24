# Development

Use `fourok-dev` for repeatable local checks. It wraps the commands that agents and
humans should run during normal development without adding another task runner.

## Fast Loop

Run the default local gate:

```bash
uv run fourok-dev fast
```

Run the same gate against a narrow pytest target:

```bash
uv run fourok-dev fast -- tests/runtime/test_compose.py -q
```

Inspect what a command will run:

```bash
uv run fourok-dev fast --dry-run
```

The command uses `.scratch/uv-cache` for uv cache state.

## Full Gate

Run the release-style local gate before claiming a broad slice done:

```bash
uv run fourok-dev full
```

This runs lint, formatting checks, file-length guard, the default pytest suite,
goal audit, and `git diff --check`.

## Test Targets

Use narrow targets while iterating:

```bash
uv run fourok-dev test tests/devtools -q
uv run fourok-dev test tests/etl/extract -q
uv run fourok-dev test tests/runtime -q
uv run fourok-dev test tests/governance tests/retrieval -q
uv run fourok-dev test tests/storage tests/runtime/test_systemd_templates.py -q
```

Use the full gate after broad runtime, workflow, schema, or docs changes.

## Hooks

Install versioned local hooks:

```bash
uv run fourok-dev install-hooks
```

The pre-commit hook runs `uv run fourok-dev fast`. The pre-push hook runs
`uv run fourok-dev full`.

## Docker

Validate Compose rendering with safe local placeholders for required variables:

```bash
uv run fourok-dev compose-config
```

This does not start containers.

Pre-pull known slow local runtime images before a verification-heavy session:

```bash
uv run fourok-dev warm-docker
```

Let slow image pulls continue when they are making progress.

## Current Baseline

On 2026-06-09, the default suite collected 527 tests and completed in about 8
seconds on the local machine, with 521 passing and 6 PostgreSQL integration
tests skipped when no test database was configured.
