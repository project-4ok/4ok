# Codex MCP Feedback — Agent Instructions

Date: 2026-06-24

Purpose: split the Codex `search_fourok` trial feedback into implementation instructions by ownership lane, enriched with the current Grafana/operator evidence from the local runtime.

## Evidence reviewed

- Codex feedback: `search_fourok` is useful and agent-native; the strongest feature is the evidence-pack `context_block`; the main risk is weak vector/semantic matches looking as authoritative as exact source-backed evidence.
- Grafana API via `uv run fourok-dev grafana-status --json`: dashboard `fourok-local-runtime-logs` is reachable, Prometheus/Loki/Tempo datasources are present, and all tracked signals are present.
- Prometheus through Grafana:
  - `fourok_retrieval_requests_total`: 54 successful retrieval calls total: 50 `keyword,vector`, 3 `vector`, 1 `keyword`.
  - `fourok_source_records_total`: Linear has 425 messages, 7 people, 702 work items; Twenty has 728 people and 797 organizations.
  - `fourok_retrieval_records_total{status="current"}`: 2684.
  - `fourok_embedding_coverage_ratio`: 0.
  - `fourok_connector_latest_run_status`: Linear succeeded; Slack, Twenty, and Google Drive failed.
- `fourok operator-status`: Linear is fresh; Slack, Twenty, and Google Drive latest live ingestion statuses are failed. Imported item counts currently only cover Linear and Twenty.
- `retrieval_query_events` DB log:
  - All 54 logged retrieval events succeeded.
  - MCP-style calls with `candidate_limit=5` returned up to 9 results; `candidate_limit=10` returned up to 20 results. This confirms Codex's observation that caller `limit` is not a hard returned-result cap when expansion/token-budget packing adds context.
  - Recent `candidate_limit=10` calls averaged 13.29 returned results; `candidate_limit=5` averaged 6.50 returned results.
- Spot checks:
  - `olivia.allen` with `candidate_limit=5` returns direct Linear comment hits containing `@olivia.allen`.
  - `Olivia` with keyword retrieval returns YC script issue hits first, then direct-context Linear people including `olivia.allen@4ok.tech`; useful, but the entity candidate is not promoted early enough for person identity questions.

## Deployment agent

Goal: make the deployed runtime expose retrieval behavior that agents can trust without local-only assumptions.

Instructions:

1. Treat `search_fourok(limit=N)` semantics as an external contract issue before wider deployment.
   - Current behavior: `limit` maps to candidate search depth/token-budget packing, not a hard result cap.
   - Required decision: either make `limit` a strict returned-result cap for MCP callers, or rename/expose it as `candidate_limit` and add `requested_limit`, `candidate_limit`, `returned_count`, and `token_budget` metadata.
   - Acceptance: an MCP regression proves `limit=5` cannot surprise a hosted/client agent, either by returning at most 5 cards or by explicitly reporting expansion semantics.

2. Preserve deployment-source freshness in the runtime API contract.
   - `search_fourok` should not require a second `operator_status` call for basic source availability.
   - Acceptance: deployed `search_fourok` responses include source scope/freshness metadata derived from the same runtime DB/operator-status source as the dashboard.

3. Add deployment smoke coverage for MCP retrieval quality, not just tool registration.
   - Smoke should call deployed `search_fourok` with one exact person query and one general topic query.
   - Acceptance: output proves tool availability, DB reachability, source freshness block, returned-count semantics, and no secrets in metadata.

4. Do not deploy a hosted MCP endpoint until the existing hosted-readiness gaps are closed.
   - HTTPS, auth, secret isolation, allowlists, rate limits, audit logging, protocol compatibility, and an operator smoke test remain required before non-loopback exposure.

## Observability agent

Goal: make Grafana/operator telemetry explain retrieval answerability, not only runtime health.

Instructions:

1. Extend retrieval telemetry from aggregate request counts to answerability and ranking diagnostics.
   - Add metrics/log fields for query type (`person_exact`, `handle_exact`, `semantic`, `mixed`), returned result count, candidate count, direct entity matches, vector-only count, and low-confidence count.
   - Acceptance: Grafana can show how often retrieval is answering from exact/entity evidence vs semantic-only evidence.

2. Add source freshness/scope panels that match `search_fourok` response metadata.
   - Current Grafana evidence shows Linear succeeded while Slack/Twenty/Google Drive failed; this materially changes the caveat agents should give.
   - Acceptance: dashboard and `search_fourok.answerability` agree on `fresh_sources`, `stale_or_failed_sources`, and `searched_sources`.

3. Add a dashboard/table for retrieval expansion surprises.
   - Use `retrieval_query_events` to show `requested_limit`, `candidate_limit`, `pre_rerank_candidates`, `distinct_sources`, and `returned_results`.
   - Acceptance: an operator can see cases like `candidate_limit=5 -> returned_results=9` and decide whether it is expected expansion or a contract bug.

4. Improve logs for MCP calls.
   - Loki currently shows Dagster/retrieval materialization logs, but no easy `search_fourok`/`operator_status` call lines.
   - Acceptance: Loki can filter MCP calls by tool name, status, result count, candidate count, duration, and audit ref without logging raw query text or secrets.

## Retrieval agent

Goal: tighten precision and trust labels while preserving the strong evidence-pack design.

Instructions:

1. Keep the `context_block` and structured result cards; they are the biggest win.
   - Do not remove `source_ref`, `source_system`, `record_type`, `title`, `occurred_at`, `snippet`, `retrievers`, `permission_refs`, or relevance labels from JSON.
   - Keep rendered agent instructions: answer only from cards, cite `source_ref`, caveat weak evidence.

2. Implement person-query ranking rules.
   - Exact email/handle/name hits first.
   - Person/entity records boosted above generic documents.
   - Direct mentions of the person next.
   - Vector-only thematic matches excluded or clearly marked weak for exact-person queries.
   - Acceptance: `Olivia` surfaces `linear:user:... olivia.allen@4ok.tech` as a likely entity candidate near the top, not only as late direct context behind YC script mentions.

3. Add top-level answerability.
   - Shape:
     - `status`: `answerable`, `partial`, `weak`, or `not_found`.
     - `confidence`: `high`, `medium`, or `low`.
     - `direct_entity_match`: boolean.
     - `fresh_sources`: list.
     - `stale_or_failed_sources`: list.
     - `searched_sources`: list.
     - `recommended_caveat`: short agent-ready sentence.
   - Acceptance: Olivia-style queries can say “partial/medium; Linear-backed only; Slack/Twenty/Drive unavailable or failed.”

4. Replace vague rerank labels.
   - Current fallback `specific source excerpt` is too broad and over-trusts generic/vector hits.
   - Preferred labels: `exact_handle_match`, `exact_email_match`, `exact_name_match`, `entity_record_match`, `direct_mention`, `semantic_similarity_only`, `mentions_related_team_members`, `query_term_absent_low_confidence`, `direct_context_for:<source_ref>`.
   - Acceptance: irrelevant vector matches never receive a label that sounds like direct evidence.

5. Improve snippet fields for agent scanning.
   - Add `evidence_quote`: shortest relevant span.
   - Add optional `surrounding_context`: longer excerpt when useful.
   - Add `matched_terms`.
   - Add `match_type`: `exact_handle`, `exact_email`, `exact_name`, `semantic`, `entity_record`, `direct_context`.
   - Acceptance: an agent can separate source-backed facts from inference without rereading long noisy snippets.

6. Add an exact-person evaluation case set.
   - Cases: `Olivia`, `olivia.allen`, full email, and one weak alias only if source-backed.
   - Acceptance: tests prove exact entity/person evidence outranks weak semantic context and answerability reports stale/failed sources.

## Onboarding / client / MCP agent

Goal: make first-use behavior obvious for agents and clients.

Instructions:

1. Update MCP tool docs/schema to match actual semantics.
   - If `limit` remains not-strict, rename it or document returned expansion explicitly in the schema description.
   - Acceptance: MCP inspector/tool schema tells callers whether `limit` means returned cards, candidates, or token budget.

2. Return client-ready source scope in `search_fourok`.
   - Distinguish `sources_searched_successfully`, `sources_unavailable_or_failed`, `sources_not_searched`, and `permissions_applied`.
   - Acceptance: clients do not need to call `operator_status` before every search just to caveat source freshness.

3. Add client guidance for answerability.
   - Document how hosted/agent clients should use `answerability.recommended_caveat`, weak labels, and entity candidates.
   - Acceptance: `docs/mcp-retrieval.md` gives one exact-person example and one stale-source caveat example.

4. Keep hosted-client warnings prominent.
   - Hosted ChatGPT/Claude cannot use loopback MCP directly.
   - Do not present local streamable HTTP as hosted-ready without HTTPS/auth/edge controls.

5. Add an onboarding smoke path.
   - After connector setup, run `operator_status`, one `search_fourok` exact-person query, and one broad retrieval query.
   - Acceptance: output says which sources are fresh, which failed, and whether the exact-person query found a direct entity.

## ETL agent

Goal: make retrieval precision possible by importing explicit entities, aliases, and freshness state.

Instructions:

1. Strengthen person/entity source records.
   - Preserve email, handle, display name, first/last name, title/role, source user ID, and source system.
   - Acceptance: `olivia.allen`, full email, and display name all resolve to the same source-backed person candidate when imported.

2. Add alias support only when source-backed.
   - Strong aliases: email, handle, exact display name, normalized name.
   - Weak aliases: nicknames such as `Liv` only when an imported source explicitly supports them.
   - Acceptance: entity candidates include `match_reason` and confidence; weak aliases are never silently treated as exact identity evidence.

3. Keep failed sources visible while allowing successful sources to remain useful.
   - Current evidence: Linear succeeded; Slack/Twenty/Google Drive failed. Retrieval should still answer Linear-backed questions while caveating missing source coverage.
   - Acceptance: ETL status writes enough source-level freshness/failure metadata for retrieval answerability and Grafana panels to agree.

4. Ensure direct-context expansion does not add misleading people.
   - Current `Olivia` result can include unrelated Linear users as direct context for YC script issues.
   - Acceptance: direct-context person records are labeled as context participants/related assignees unless they directly match the query.

5. Feed retrieval with matchable entity fields.
   - Index canonical/person fields separately enough for exact name/handle/email matching before semantic retrieval.
   - Acceptance: exact-person retrieval works even when vector embeddings are missing or coverage is zero.

## Cross-agent priority order

1. Retrieval: fix exact-person ranking, answerability, honest labels, and strict/explicit limit semantics.
2. Observability: expose source freshness and returned-vs-requested retrieval behavior in Grafana/Loki.
3. ETL: enrich person/entity alias fields and source freshness metadata required by retrieval.
4. Onboarding/MCP: update schema/docs and add client smoke examples once semantics are decided.
5. Deployment: carry the proven MCP/retrieval contract into deployed runtime smoke checks.
