# fourok MCP Server — Instructions

Use fourok as the source-backed context layer for company, project, customer, connector, Slack, Linear, email, CRM, and operational questions. Do not answer those questions from model memory or chat history alone when fourok tools are available.

## Required agent flow

1. For source-backed company-context questions, call `fourok.retrieve` before answering with a short evidence-shaped query.
2. If retrieved results look relevant, call `fourok.open` on the best `source_ref` values before making detailed claims or quoting specifics. Pass `retrieval_event_id` and `rank` when the retrieve response provides them so fourok can learn organic relevance signals.
3. Ground the response in returned evidence. Cite durable refs such as `source_ref`, `audit_ref`, and `inspection_event_id` when making evidence-backed claims.
4. If retrieval returns no useful results, say "No retrieved evidence matched" rather than claiming the fact does not exist. Then call `fourok.status` if setup or freshness may be the issue.
5. Use `fourok.onboard` only for setup/repair guidance, not as a substitute for retrieval.

## Good retrieval queries

- `current renewal risks`
- `Slack connector freshness errors`
- `latest Acme escalation`
- `retrieval MCP setup`

## Safety and scope

- Never include secrets, raw `.env` values, database URLs, tokens, or private keys in retrieval queries.
- Treat retrieved cards as evidence, not a final-answer oracle. Reason over them and separate evidence from inference.
- Respect limitations returned by the tool, especially freshness, permission filtering, and empty-result caveats.
