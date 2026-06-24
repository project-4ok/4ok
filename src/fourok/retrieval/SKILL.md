---
name: fourok-retrieval
description: Use when working in the fourok repo and you need source-backed project/company context, imported Slack/Linear/email/CRM evidence, retrieval status, or agent-facing retrieval proof. Prefer native MCP when already configured; otherwise use the repo CLI as the stable backend.
version: 1.0.0
author: fourok
license: MIT
metadata:
  hermes:
    tags: [fourok, retrieval, cli, mcp, evidence, agents]
    related_skills: [fourok-repo-development, native-mcp]
---

# fourok Retrieval

## Overview

fourok retrieval gives agents a source-backed, permission-filtered evidence layer for project and company context. It is not generic memory and it is not a final-answer oracle. Treat retrieved cards as evidence to reason from, cite with `source_ref` or `audit_ref`, and say when retrieval returned no relevant evidence.

Default backend for coding agents is the CLI because it works in any checked-out repo without a Hermes restart. Native MCP is preferred only when the MCP tool is already present in the current session.

## When to Use

Use this when:

- The user asks what fourok knows about a project, source, Slack/Linear item, customer, connector, current priority, decision, or operational context.
- You need evidence before answering from repo/imported context.
- You are about to summarize retrieved company context for a human or another agent.
- You need to verify that retrieval itself is healthy or populated.

Do not use this for:

- General code search inside the checkout; use `search_files` and `read_file`.
- External/current web facts; use web/search tools.
- Secrets or credentials; never print `.env`, database URLs, tokens, or connector secrets.
- Claims that require live connector success unless you also run the relevant live/import/status proof.

## Backend Selection

1. Prefer MCP when native MCP tool `mcp_fourok_retrieval_search_fourok` or an equivalent `search_fourok` tool is available in the current Hermes session; otherwise use CLI from the repository root.
2. If Docker Compose is running but CLI context is unavailable, use the HTTP MCP endpoint only with a local MCP client.
3. If neither CLI nor MCP is available, say retrieval is unavailable and what command would enable it.

## CLI Backend

Run from the repo root:

```bash
uv run fourok retrieve "<query>" --format json
```

For an LLM-ready evidence block instead of JSON:

```bash
uv run fourok retrieve "<query>"
```

For explicit local SQLite state:

```bash
uv run fourok retrieve "<query>" --state .local/fourok-state.sqlite --format json
```

For runtime/Postgres state, rely on server-side env or pass a redacted-safe runtime URL only when already configured in the environment:

```bash
uv run fourok retrieve "<query>" --database-url "$FOUROK_DATABASE_URL" --format json
```

Check retrieval/runtime population:

```bash
uv run fourok operator-status --format json
```

Read this skill directly at `src/fourok/retrieval/SKILL.md`; it is intentionally
not a product CLI command.

## MCP Backend

Local Docker Compose starts streamable HTTP MCP at:

```text
http://127.0.0.1:8010/mcp
```

Expected tools:

- `search_fourok`
- `operator_status`

Use MCP when it is already configured as a first-class Hermes tool. Prefer the CLI fallback if the current session has not discovered MCP tools yet; Hermes usually needs a restart/new session after MCP config changes.

## Reading Results

CLI JSON from `retrieve` includes at least:

- `status`: retrieval status such as `ok`.
- `context_block`: prompt-ready evidence block.
- `results`: source evidence cards.
- `limitations`: retrieval caveats.

MCP `search_fourok` includes structured fields such as:

- `results`
- `summary`
- `result_candidates`
- `evidence_items`
- `primary_objects`
- `related_objects`
- `entities`
- `limitations`
- `audit_ref`

Always cite durable refs when using retrieval evidence:

```text
source_ref: slack:message:...
audit_ref: audit:search:...
```

If `results` is empty, say "No retrieved evidence matched" rather than "nothing exists". Empty retrieval can mean the state is fresh, permissions filtered records out, connectors have not run, or the query needs different wording.

## Query Guidance

Good queries are short and evidence-shaped:

```text
refund cancellation follow-up
current fourok retrieval mcp setup
Slack connector freshness errors
Linear current priorities
```

Avoid pasting long prompts or secrets into the query. Do not include credentials, private keys, raw `.env` values, or customer secrets.

## Verification Commands

```bash
uv run pytest tests/retrieval/test_agent_skill.py tests/retrieval/test_retrieve_cli.py tests/retrieval/test_api_king.py -q
uv run fourok retrieve "retrieval mcp setup" --format json
uv run fourok operator-status --format json
```

## Common Pitfalls

1. Assuming MCP is available in the current Hermes session after editing config. It is not hot-loaded; use CLI or restart Hermes.
2. Treating retrieved text as a final answer. Retrieval provides evidence; the agent still has to reason and cite.
3. Claiming no evidence exists from an empty result set. Say no retrieved evidence matched and include status/limitations.
4. Printing raw database URLs or connector credentials. Keep secrets server-side and redact env-derived values.
5. Using session history before retrieval for imported fourok/company context. If the question is about source-backed fourok knowledge, retrieve first.
6. Confusing local loopback MCP with hosted ChatGPT/Claude readiness. Hosted clients still need HTTPS, auth, allowlists, rate limits, and public smoke tests.

## Verification Checklist

- [ ] Ran retrieval from the repo root or used an already-discovered MCP tool.
- [ ] Checked `status`, `results`, `limitations`, and `audit_ref` where present.
- [ ] Cited `source_ref` / `audit_ref` for evidence-backed claims.
- [ ] Did not print secrets, raw database URLs, or connector credentials.
- [ ] Clearly separated retrieved evidence from inference.
