# Context Substrate Map

Working notes for choosing what to patch together from existing tools and what
the project still needs to own.

## First Principles

The product is governed company context retrieval, not agent memory.

The system needs:

- immutable source records as ground truth
- source refs, timestamps, provenance, lifecycle, and permissions
- entity mentions and entity-link decisions
- canonical entities or candidate clusters across source systems
- hybrid retrieval over permitted evidence
- answer synthesis from evidence, with citations
- controlled reveal and audit later

Do not make summaries, memories, peer cards, or graph facts the source of
truth. They are indexes, caches, or derived views over source evidence.

## Main Learning

Peer-centric memory is the wrong primary abstraction for company context.

Honcho is useful when the question starts with a known participant:

```text
what does this user or agent know, prefer, or remember?
```

Company context often starts differently:

```text
which source records, entities, facts, and relationships answer this question?
```

That means retrieval should usually discover evidence first, then scope and
summarize. Honcho tends to scope by peer/session before reasoning.

## Entity Linking Pattern

The promising pattern is not a single global LLM decision.

Use:

```text
source episode
  -> extracted mentions
  -> candidate generation
  -> deterministic matching
  -> bounded LLM resolution where needed
  -> stored link decision with evidence
```

Strong deterministic signals:

- source-native IDs
- normalized email addresses
- CRM object IDs
- Slack/Linear/Twenty user IDs mapped by email
- exact normalized names where candidate set is unambiguous

Useful probabilistic signals:

- name similarity
- alias similarity
- shared domain
- signature block proximity
- repeated co-occurrence
- relation to known company, project, or thread

Keep identity links separate from association links:

```text
same_identity_candidate: Robin Scharf == robin@example.com
association: Linear issue mentions Robin
association: Olivia created Linear issue
```

Co-occurrence should strengthen association evidence by default. It should only
contribute to identity merging when the evidence type is strong enough.

## Tool Map

| Tool | Good At | Gaps For This Project | Current Use |
|---|---|---|---|
| Graphiti | Temporal entity/fact graph, episodes as provenance, incremental updates, custom entity/edge types, hybrid graph search | Governance and permissions remain ours; entity linking quality must be tested on our sources; public ingestion paths do not preserve arbitrary episode metadata, so source refs must be encoded or stored externally | Strong candidate for context graph experiment, but provenance fit is now a key risk |
| Zep | Managed Graphiti-like context infrastructure, production APIs, context assembly, enterprise features | No access for this goal; managed dependency; governance fit and metadata/ACL model would still need validation | Research context only for current goal |
| Neo4j | Explicit entity graph, graph traversal, custom modeling, relationship queries | We build extraction, linking, indexing, governance, and retrieval orchestration ourselves | Good if we need maximum control |
| LlamaIndex | Parsing, source nodes, retriever composition, citation-oriented synthesis, property graph helpers | Not a governed context substrate alone; entity resolution and permissions are custom | Useful orchestration/retrieval library |
| LangGraph | Agent/workflow orchestration and stateful tool flows | Not source/evidence storage or entity linking | Useful for agent-side query workflow later |
| Honcho | User/agent/participant memory, peer representations, conversation continuity | Peer/session scoping fights company-wide evidence discovery; no native entity discovery; source provenance is not the main abstraction | Keep as OpenClaw/user memory experiment, not primary company brain |
| OpenViking | Resource-centric context filesystem, URIs, hierarchical retrieval | Entity linking and governance still ours; less clearly a temporal entity/fact graph | Optional docs/resource layer to revisit |
| Microsoft GraphRAG | Batch corpus summarization, themes, communities, broad sensemaking | Less suited to live day-2 enterprise records, permissions, and precise evidence lifecycle | Possible secondary analysis layer |
| Meltano/Singer | Connector execution, state/checkpoint patterns, existing taps | Source permissions and rich domain semantics often incomplete | Use where connector output is sufficient |
| Env/.env | Secret retrieval and runtime credential management | Product auth/policy still separate | Use for runtime connector credentials |
| Presidio | PII recognizers and tokenization pipeline support | Domain-specific detection quality still needs tests | Current PII baseline |
| Docling/unstructured | Document/PDF parsing and OCR pipeline candidates | Large footprint and extraction quality need isolated validation | Containerized experiments only for now |

## What Existing Tools Can Own

Likely outsource:

- source connector state where Singer taps are good enough
- secret delivery through env/.env or external runtime injection
- graph episode/entity/fact extraction experiment through Graphiti OSS
- graph storage/traversal through Graphiti backend or Neo4j
- retrieval orchestration pieces through LlamaIndex where useful
- PII detection baseline through Presidio
- agent workflow orchestration through LangGraph if needed

## What We Still Need To Own

Product-owned surface:

- source record normalization and stable source refs
- connector-specific permission/lifecycle mapping
- entity-link decision policy and audit trail
- confidence thresholds and human review workflow
- governed retrieval API contract
- evidence pack shape and citation rules
- PII tokenization and reveal workflow
- deletion/restriction propagation across derived layers
- operations, backup/restore, scheduler, and deployment shape

Even if Graphiti or Zep handles entity extraction and deduplication, the project
still owns whether a link is trusted enough for a governed answer.

## Current Architecture Hypothesis

The likely product shape is:

```text
connectors
  -> source_records
  -> source episodes
  -> entity/fact substrate experiment
       - Graphiti OSS or Neo4j-backed custom graph
  -> hybrid retrieval
  -> evidence pack
  -> answer synthesis
  -> reveal policy and audit
```

For now:

- keep Honcho as a side experiment for OpenClaw/user continuity
- stop designing company context around Honcho peers
- test Graphiti against the same Linear + Twenty data
- compare entity linking, source provenance, and retrieval quality

Current retrieval evidence:

- `gcb eval-retrieval` runs local golden-query cases through active governed
  context retrieval
- the check verifies expected source refs, evidence pack assembly, and search
  audit refs
- categories cover exact employee linking, ambiguous Robin references,
  retrieval/provenance, governance metadata compatibility, chat-acquired
  knowledge, and day-2 lifecycle
- the hidden `gcb evidence-baseline-eval` command keeps the old custom baseline
  available as a comparison floor

Current Graphiti wiring:

- `graphiti-runner` is an isolated Dockerfile/script experiment, not an active
  Docker Compose runtime service
- it installs `graphiti-core==0.29.1` from PyPI outside the main app image
- `zepai/graphiti:latest` exists but is the packaged server image, not the
  custom evaluation runner
- it ingests the same 15-case fixture through the Graphiti Python API
- measured run ingested 19 episodes and returned relevant semantic facts
- earlier default Graphiti fact search scored 0/14 on the evidence contract
  because useful facts did not include source refs, entity refs, or permission
  refs
- the provenance wrapper joins returned edge episode UUIDs back to source
  episode metadata and improved the earlier eval to 7/14
- provenance recovery works when Graphiti returns facts with linked episode
  UUIDs; it still fails when useful inferred facts have no usable source edge in
  the result shape
- adding source-record fallback improves the current eval to 15/15, but
  fallback is used in all 15 cases; the latest report shows
  `graphiti_only_passed: 7`, `source_fallback_cases: 15`, and
  `source_fallback_items: 56`
- source records are carrying the evidence contract; Graphiti contributes useful
  semantic/fact recall in less than half of the current fixture cases
- Graphiti is best treated as a derived semantic/fact index unless later tests
  show it can consistently return provenance and lifecycle metadata directly

Current Honcho comparison:

- Dockerized app image `4ok-app:47d077b6acd9`
- fixture sync wrote 7 Honcho messages into a fresh workspace
- workspace search scored 7/15, with 6/15 top-1 hits and 7/15 top-3 hits
- passed ambiguous message retrieval and day-2 message cases
- missed employee catalog, governance metadata, broad project/team retrieval,
  and one chat-acquired knowledge case
- keep Honcho as OpenClaw/user continuity memory, not primary company context
  retrieval

## Next Experiments

1. Product evidence API:
   turn the source-record-first baseline into the concrete `search_context`
   evidence-pack shape.
2. Policy-filtered retrieval:
   apply permission metadata before retrieval and record allow/deny behavior.
3. Entity-linking quality test:
   check real Twenty CRM aliases, companies, projects, and first-name ambiguity
   against expected candidates.
4. Graphiti value test:
   measure whether Graphiti improves recall/ranking enough to justify running
   it as a derived index.
5. Live-data replay:
   rerun the 15-case shape against bounded live Linear/Twenty/Slack-derived
   data and record failures by cause.
