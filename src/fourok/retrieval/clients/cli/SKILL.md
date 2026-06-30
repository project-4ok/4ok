---
name: fourok-retrieval
description: Use the fourok CLI to retrieve source-backed company/project context before answering.
version: 1.0.0
author: fourok
license: MIT
metadata:
  hermes:
    tags: [fourok, retrieval, cli, evidence, agents]
---

# fourok Retrieval

## Overview

fourok retrieval gives agents a source-backed, permission-filtered evidence layer for project and company context. It is not generic memory and it is not a final-answer oracle. Treat retrieved cards as evidence to reason from, cite with `source_ref`, `audit_ref`, or `inspection_event_id`, and say when retrieval returned no relevant evidence.

## When to Use

Use this when:

- The user asks what fourok knows about a project, source, Slack/Linear item, customer, connector, current priority, decision, or operational context.
- You need evidence before answering from imported company context.
- You are about to summarize retrieved company context for a human or another agent.
- You need to verify that retrieval itself is healthy or populated.

Do not use this for general code search, external/current web facts, or secrets.

## CLI Backend

Run from an environment where the `fourok` CLI is configured:

```bash
fourok retrieve "<query>" --json
```

For an LLM-ready evidence block instead of JSON:

```bash
fourok retrieve "<query>"
```

Open decisive sources before detailed claims:

```bash
fourok open <source_ref> --retrieval-event-id <event_id>
```

Check retrieval/runtime population:

```bash
fourok status
```

Get setup/repair guidance:

```bash
fourok onboard
```

## Reading Results

CLI JSON from `retrieve` includes at least:

- `status`: retrieval status such as `ok`.
- `context_block`: prompt-ready evidence block.
- `results`: source evidence cards.
- `limitations`: retrieval caveats.

Always cite durable refs when using retrieval evidence:

```text
source_ref: slack:message:...
audit_ref: audit:search:...
inspection_event_id: retrieval-inspection:...
```

If `results` is empty, say "No retrieved evidence matched" rather than "nothing exists". Empty retrieval can mean the state is fresh, permissions filtered records out, connectors have not run, or the query needs different wording.

## Query Guidance

Good queries are short and evidence-shaped:

```text
refund cancellation follow-up
current fourok retrieval setup
Slack connector freshness errors
Linear current priorities
```

Avoid pasting long prompts or secrets into the query. Do not include credentials, private keys, raw `.env` values, database URLs, or customer secrets.

## Verification Checklist

- [ ] Ran retrieval through `fourok retrieve`.
- [ ] Opened decisive sources with `fourok open` before detailed claims.
- [ ] Checked `status`, `results`, `limitations`, and refs where present.
- [ ] Cited `source_ref` / `audit_ref` / `inspection_event_id` for evidence-backed claims.
- [ ] Did not print secrets, raw database URLs, or connector credentials.
- [ ] Clearly separated retrieved evidence from inference.
