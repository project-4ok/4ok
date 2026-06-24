# Agent Engineering Rules

Telegraphic style. Root rules only. Keep this file short, scannable, and project-independent.

## Start

- Run `git status --short` before edits.
- Read relevant docs only; avoid broad context loading.
- Verify dependency-backed behavior from upstream docs/source/types before relying on it.
- Never print secrets.
- Do not use in-repository worktrees. For orchestrated GCB Codex implementation, use only project-adjacent worktrees such as `../4ok.worktrees/<task-slug>/`.
- Do not use `/tmp` for project artifacts, datasets, state, or experiment outputs; use a project-local ignored scratch directory.
- Use `.reference` only as a local, read-only research shelf for external repositories.
- Never import code from `.reference`, copy files from it into the product, mount it
  into containers, or depend on it from application code, Dockerfiles, tests, or
  runtime configuration.
- Treat `.reference` findings as research notes; production/runtime inputs must come
  from tracked source, packaged dependencies, or maintained upstream images.

## Loop

```text
acceptance criterion -> failing test/check -> smallest change -> refactor -> live/operator proof -> summarize
```

- For non-trivial GCB coding, Hermes may implement small/medium changes directly.
- Use Codex when 2-4 independent slices can run in parallel, or when one task is large enough to justify worktree/prompt/review overhead.
- Spawn supervised Codex worker processes/sessions for large independent implementation; use Hermes subagents for parallel research/review.
- Launch Codex workers with explicit model `gpt-5.3-codex-spark`; do not use fast mode/service-tier fast or the Codex default model for GCB implementation work.
- Codex worker prompts must include scope, TDD/proof command, commit policy, and a durable `.local/codex-runs/<slug>/` report path.
- Keep adjacent Codex worktrees tidy: after integrating or rejecting a worker, remove its worktree/branch once evidence is preserved; before launching more than a few workers, run `git worktree list` and prune stale directories under `../4ok.worktrees/`.

- Treat executable acceptance criteria as the primary prompt for coding agents.
- Write non-trivial requirements in Given/When/Then or equivalent observable form
  before implementation.
- Prefer one small behavior slice with a clear proof command over broad prose tasks.
- Prefer small vertical slices over broad infrastructure.
- Make exploratory work answer an explicit question.
- Keep diffs small and reviewable.
- Do not mix refactors with behavior changes unless necessary.
- When progress feels slow, shrink the active gate before adding workers or scope.
- Use parallel Codex for independent coding only; use 1 implementer + 1 reviewer
  when the bottleneck is live evidence, integration, or stale acceptance data.

## Domain Agents

Use these ownership lanes to run multiple agents with minimal conflicts:

- Import pipeline agent: `src/gcb/etl/extract/`, connector fixtures/tests, live-contract scripts. Output valid `SourceRecord`s; avoid retrieval/ranking changes.
- Source-record/storage agent: `src/gcb/storage/`, source-record schemas, migrations/contracts. Coordinate before changing shared columns or table semantics.
- Entity-linking/context agent: `src/gcb/etl/load/context_objects.py`, canonical object/entity-link tests, future `src/gcb/context_graph/`. Consume source records; avoid connector code.
- Retrieval/reranker agent: `src/gcb/retrieval/`, `tests/retrieval/`, retrieval CLI/eval tests. Consume retrieval records; avoid import adapters and Dagster wiring unless needed for proof.
- Runtime/orchestration agent: `src/gcb/runtime/`, `src/gcb/orchestration/`, `deploy/dagster/`, `deploy/observability/`, `docker-compose.yml`, operator scripts. Keep orchestration thin; avoid domain algorithm changes.
- CLI/agent-experience agent: `src/gcb/cli_parts/`, CLI tests, OpenClaw-facing docs/tools. Do not change storage/retrieval internals without a domain owner.
- Governance/security agent: `src/gcb/governance/`, permission/retention/audit tests. Review any cross-domain permission or sensitive-data change.

If two agents need the same lane, shrink the slice or serialize. Schema/storage and Dagster orchestration are shared choke points; treat them as coordination gates.

## TDD

- Write/update a failing behavioral test, golden output, or executable acceptance
  check before implementation.
- Run the narrow check and verify the expected RED failure before production code.
- Implement only enough to pass.
- Re-run the narrow check and verify GREEN before refactoring.
- Add regression tests before bug fixes.
- Test observable behavior, durable state, CLI/API/runtime contracts, and operator
  outputs; avoid private helper names, call order, or incidental structure.
- For agent/Codex work, require the worker to state why the new check fails on
  the old behavior and why passing proves the requested behavior.
- If test-first is impractical, say why and add the smallest executable check
  before claiming the slice is complete.

## Acceptance Checks

- Prefer reusable project commands for acceptance proof, especially for runtime,
  connector, retrieval, observability, and permission behavior.
- Acceptance commands should return deterministic pass/fail output, ideally JSON,
  and exit non-zero on failure.
- Keep three proof layers distinct:
  1. deterministic regression test for the behavior;
  2. runtime/operator acceptance command for the local system surface;
  3. live-data evidence when credentials/runtime access are expected to work.
- Fixture or synthetic tests may prove edge cases, but they do not replace live
  connector/import/retrieval proof when the claim is about real local data.
- For GCB runtime work, prove the same surface a human or agent will use:
  Dagster, operator CLI/status, Grafana/Loki/Tempo/Prometheus, MCP tools, and
  permission allow/deny paths as applicable.
- Keep acceptance data current. If a live case fails because expected source refs
  or fixtures are stale, refresh/review the case set before treating product code
  as broken.
- Prefer one executable stage acceptance command over scattered report prose.

## Quality Gates

- Proactively create git hooks when implementation begins if none exist.
- Pre-commit: formatting + relevant unit tests minimum; add lint and secret/artifact guards when available.
- Pre-push: full test suite; add integration/golden/migration/security checks when relevant.
- Do not bypass hooks unless explicitly instructed.
- Before handoff: prove the touched surface. If proof is blocked, say exactly what is missing.

## Continuous Delivery

- Use trunk-based development with one source-of-truth branch.
- Do not create feature branches or merge-request workflows unless explicitly instructed.
- Work in small batches and integrate frequently.
- Make commits atomic: each commit should contain one coherent behavior, documentation, or tooling change.
- Do not bundle unrelated fixes, refactors, formatting churn, or experiments into the same commit.
- Treat each completed vertical slice as a commit trigger.
- Before starting a new slice, run `git status --short`; if the previous slice is verified and uncommitted, commit it first.
- Use `git diff --stat` as a size trigger: when the uncommitted diff grows beyond roughly 200 changed lines, stop and consider whether a verified atomic commit should be made before continuing.
- Commit immediately after verification when a slice changes behavior, docs, dependencies, schema, fixtures, or workflow.
- Do not let more than one coherent slice remain uncommitted unless the user explicitly asks to defer commits.
- If work is interrupted, resume by checking whether the current diff can be split into already-verified atomic commits before writing more code.
- Keep the system releasable.
- Automate repeatable checks.
- Keep run/deploy/reproduction steps scripted.
- Trace meaningful changes to a test, experiment, issue, or decision.

## Complexity

Software engineering is complexity management.

- Prefer mature libraries, standard tools, and OSS when they reduce real complexity.
- Do not outsource product judgment, security, or policy decisions to a library.
- Every change should add required behavior, reduce future change cost, improve testability/observability, or remove unnecessary surface area.
- Prefer files under 800 lines; split before 1200 unless documented.
- Keep public interfaces narrow and stable.
- Avoid abstractions until repeated behavior proves they are needed.
- Make data flow explicit; hidden coupling is complexity.
- Prefer composition over large multipurpose modules.
- Delete unused code, dead paths, and speculative extension points.
- New abstractions, dependencies, config paths, services, schema fields, or workflow steps must pay for themselves with reduced product or operational complexity.

## Changeability

Optimize for future change, not only current correctness.

Before non-trivial implementation, estimate:

- files touched
- tests/checks needed
- new concepts introduced
- docs/migration impact

After implementation, compare actual scope to expected. If scope grew sharply, record why in `docs/review.md`.

Watch for complexity pressure:

- small behavior changes touch unrelated files
- tests need excessive setup or brittle mocks
- one new case requires copied logic
- a module has multiple reasons to change
- behavior depends on hidden ordering, globals, or side effects
- names no longer match behavior
- fixtures are larger than the behavior they prove
- refactoring feels risky because tests check internals
- normal control flow needs detailed comments

When pressure appears:

- stop adding surface area
- add/improve behavior tests before refactoring
- simplify or delete before abstracting
- extract only around proven duplication or unstable decisions
- split modules by responsibility, not technical layer alone
- append a review note when the tradeoff needs later audit

## Code

Prefer:

- explicit module boundaries
- simple functions
- stable command names
- typed data structures where practical
- deterministic outputs and ordering
- early returns over nested condition pyramids
- named intermediates for domain meaning
- clear errors that fail loudly
- small fixtures and golden files
- stable domain names over generic names
- explicit data models at boundaries
- narrow adapters around external tools
- policy/config at edges, not scattered conditionals

Avoid:

- hidden global state
- unnecessary dynamic imports
- broad catch-all exceptions
- silent fallback behavior
- premature abstractions
- duplicated helpers
- large unreviewable diffs
- temp-variable soup
- speculative plugin systems
- generic manager/service objects without one clear responsibility
- flags that create many hidden behavior combinations

## Errors

- Bad config should stop execution rather than produce wrong output.
- Partial recovery is allowed only when documented, visible, and test-covered.
- Public/hostile input deserves care; hypothetical malformed input does not justify broad fallback stacks.

## Dependencies

Before adding a dependency, check:

- license
- maintenance status
- why existing tools are insufficient
- operational/deployment impact
- security or compliance impact

Call out new dependencies in the final response.

## Integrations

- Before adding or wiring an external runtime, connector, SDK, plugin, API, or
  service, create a small executable contract proof.
- Prove auth, read/write shape, idempotency, metadata support, Docker/runtime
  shape, and failure behavior before main-pipeline integration.
- Keep the proof as a test, smoke command, fixture, or documented check.
- Do not assume docs match runtime behavior when a cheap live/local proof is
  possible.
- Do not claim connector/import coverage from extracted text alone; unsupported
  file/message types still need metadata records, permissions, limitations, and
  operator-visible counts when they are in scope.
- Add unresolved integration risks to `docs/review.md`.

## Docker

- Prefer pulling maintained public images over building local images.
- Let slow image pulls or dependency downloads continue when they are making
  progress; do not abort them just because they take several minutes.
- Before adding a custom Docker build, check whether an upstream image can be
  used directly or as a base; for external runtimes such as Graphiti, research
  available public images before writing or extending a Dockerfile.
- Never build or tag project Docker images as `latest`.
- Tag images with the current commit hash so runtime state is identifiable.
- If a Docker image would include uncommitted changes, commit the slice first or
  clearly keep the image as local scratch only.

## Data

Never commit:

- real customer/user data
- secrets or credentials
- local databases
- generated indexes
- large generated artifacts
- project-local scratch directories
- raw third-party datasets unless explicitly approved

Small synthetic fixtures are OK when clearly fake and useful for tests.

## Docs

- Source code and executable tests are the source of truth for implemented behavior.
- Docs are for unimplemented plans, operator commands, architectural decisions, and risks.
- Do not duplicate implemented behavior across many docs; link to code/tests or one owning doc.
- Delete or shrink docs when implementation makes them redundant.
- New workflows need purpose, command, expected output, test/check command, and limitations.
- Keep decisions short and evidence-linked.

## Goal File

- Use `docs/goal.md` for the active product goal/backlog, not session history.
- Write every requirement as a checkbox item: `- [ ] requirement`.
- Keep checklist items observable: each should have a clear proof, test, command,
  artifact, or decision that can make it `[x]`.
- Keep the active goal small: current gates only. Move completed proof detail to
  reports and review notes.
- Separate process rules, current state, evidence logs, and product requirements;
  do not let `docs/goal.md` become the handoff transcript.
- For long-running work, maintain a concise current-state note when useful:
  open gates, last verified command, blocker, next command.
- Split large requirements into smaller checkboxes before implementation.
- Group checkboxes by phase or responsibility when that reduces scanning cost.
- Update checkbox status as slices are completed and verified.
- Do not mark an item complete because code exists; mark it complete only after
  its required proof has passed or the decision is documented.
- Move completed historical detail out of `docs/goal.md`; keep the file focused
  on current or future work.

## Human Review Log

Append review items to:

```text
docs/review.md
```

Continue when a reasonable path is clear. Add entries for:

- security or permissions
- sensitive data handling
- retention or deletion
- schema/migrations
- external services
- restrictive licenses
- destructive commands
- production deployment behavior
- reduced observability/auditability

## Verify Before Final

For code changes:

- run relevant tests/checks
- run format/lint if configured
- run `git diff --check`
- state what passed and what was not verified

For docs-only changes:

- run `git diff --check`
- inspect changed docs for consistency
