# fourok CLI Client Instructions

Use the fourok CLI as the stable source-backed context client for agents.

## Required flow

1. For source-backed company, project, customer, connector, Slack, Linear, email, CRM, or operational questions, run `fourok retrieve "<query>" --json` before answering.
2. If retrieved results look relevant, run `fourok open <source_ref>` for decisive sources before making detailed claims, quotes, or behavioral inferences. Pass `--retrieval-event-id` when available so fourok can infer the opened rank from the retrieved source.
3. Cite durable refs such as `source_ref`, `audit_ref`, and `inspection_event_id`.
4. If no useful result is returned, say "No retrieved evidence matched" and use `fourok status` when setup or freshness may be the issue.
5. Use `fourok onboard` only for setup/repair guidance.

## Commands

```bash
fourok status
fourok retrieve "<query>" --json
fourok open <source_ref>
fourok onboard
```

Never put secrets, raw `.env` values, database URLs, tokens, or private keys in retrieval queries.
