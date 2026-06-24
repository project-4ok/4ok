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
| Zep | Managed temporal context infrastructure, production APIs, context assembly, enterprise features | No access for this goal; managed dependency; governance fit and metadata/ACL model would still need validation | Research context only for current goal |
| Neo4j | Explicit entity graph, graph traversal, custom modeling, relationship queries | We build extraction, linking, indexing, governance, and retrieval orchestration ourselves | Good if we need maximum control |
| LlamaIndex | Parsing, source nodes, retriever composition, citation-oriented synthesis, property graph helpers | Not a governed context substrate alone; entity resolution and permissions are custom | Useful orchestration/retrieval library |
| LangGraph | Agent/workflow orchestration and stateful tool flows | Not source/evidence storage or entity linking | Useful for agent-side query workflow later |
| Honcho | User/agent/participant memory, peer representations, conversation continuity | Peer/session scoping fights company-wide evidence discovery; no native entity discovery; source provenance is not the main abstraction | Future retrieval-fusion sidecar for agent long-term memory, not primary company brain |
| OpenViking | Resource-centric context filesystem, URIs, hierarchical retrieval | Entity linking and governance still ours; less clearly a temporal entity/fact graph | Optional docs/resource layer to revisit |
| Microsoft GraphRAG | Batch corpus summarization, themes, communities, broad sensemaking | Less suited to live day-2 enterprise records, permissions, and precise evidence lifecycle | Possible secondary analysis layer |
| Meltano/Singer | Connector execution, state/checkpoint patterns, existing taps | Source permissions and rich domain semantics often incomplete | Use where connector output is sufficient |
| external secret manager | Secret retrieval and runtime credential management | Product auth/policy still separate | Use for runtime connector credentials |
| Presidio | PII recognizers and tokenization pipeline support | Domain-specific detection quality still needs tests | Current PII baseline |
| Docling/unstructured | Document/PDF parsing and OCR pipeline candidates | Large footprint and extraction quality need isolated validation | Containerized experiments only for now |

## What Existing Tools Can Own

Likely outsource:

- source connector state where Singer taps are good enough
- secret delivery through external secret manager
- graph storage/traversal through Neo4j or another source-record-compatible graph layer
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

Even if an external graph layer handles entity extraction and deduplication, the
project still owns whether a link is trusted enough for a governed answer.

## Current Architecture Hypothesis

The likely product shape is:

```text
connectors
  -> source_records
  -> source episodes
  -> entity/fact substrate experiment
       - Neo4j-backed custom graph or another source-record-compatible graph
  -> hybrid retrieval
  -> evidence pack
  -> answer synthesis
  -> reveal policy and audit
```

For now:

- stop designing company context around Honcho peers
- compare entity linking, source provenance, and retrieval quality using the
  source-record-first retrieval path
- keep future Honcho work as a retrieval-fusion feature: a short memory section
  may be appended to retrieval responses after governed evidence is assembled

Current retrieval evidence:

- `fourok eval-retrieval` runs local golden-query cases through active governed
  context retrieval
- the check verifies expected source refs, evidence pack assembly, and search
  audit refs
- categories cover exact employee linking, ambiguous Robin references,
  retrieval/provenance, governance metadata compatibility, chat-acquired
  knowledge, and day-2 lifecycle


## Next Experiments

1. Product evidence API:
   turn the source-record-first baseline into the concrete `search_context`
   evidence-pack shape.
2. Policy-filtered retrieval:
   apply permission metadata before retrieval and record allow/deny behavior.
3. Entity-linking quality test:
   check real Twenty CRM aliases, companies, projects, and first-name ambiguity
   against expected candidates.
4. Live-data replay:
   rerun the 15-case shape against bounded live Linear/Twenty/Slack-derived
   data and record failures by cause.
