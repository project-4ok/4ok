# Practical architecture for entity identification and linking in agent context systems

## Executive summary

For a workspace-context agent, the core design problem is not retrieval first; it is **identity before retrieval**. In your setting, the system must resolve mentions in unstructured text, consolidate structured records across SaaS systems, preserve provenance from raw source objects, and only then decide what should update long-term memory. That means you need **both** mention-level entity linking and catalog-level entity resolution. Named entity recognition helps detect and type mentions in text, but it is not enough on its own; record linkage and entity resolution are what reconcile CRM contacts, Slack users, Google Workspace users, Linear users/projects, repos, services, and previously unseen entities into a stable canonical layer. Classical and modern EL literature converge on the same pipeline shape: candidate generation, context encoding, candidate ranking, and optional NIL or unlinkable handling. Record-linkage literature converges on blocking or candidate selection, pair comparison, and match classification. In your problem, those pipelines have to be combined into one enterprise identity service. citeturn29view2turn29view3turn31view0turn29view1turn34view3

The most practical architecture is a **four-layer system**. First, keep an append-only raw event/object journal keyed by source-native IDs. Second, maintain a canonical entity registry with aliases, source references, and merge history. Third, run a linker service that scores links using deterministic rules first, probabilistic models second, and optional LLM reranking only over a bounded candidate set. Fourth, expose linked data to both entity-centric retrieval and memory systems such as Honcho, but only after confidence gating. This separation matters because Honcho is peer-centric and updates peer representations from messages; if you write an ambiguous event to the wrong peer, you do not just create a bad index entry, you teach the memory layer the wrong thing about that entity. Honcho’s docs explicitly describe messages as triggering background reasoning that updates peer representations across sessions. citeturn38view0turn38view1

My recommendation for an MVP is to stay mostly deterministic: use PostgreSQL as the system of record, model entities and edges in relational tables, use exact IDs, emails, domains, and alias dictionaries first, then use trigram or fuzzy search plus a small probabilistic classifier for ambiguous cases. Introduce LLMs only for bounded top-k reranking or summarization after linking, never for unconstrained entity creation or free-form canonical writes. Add Neo4j only when graph-neighborhood features and multi-hop queries become central enough that relational joins and edge tables are a bottleneck in either correctness or developer ergonomics. GraphRAG is relevant, but mostly **downstream** for retrieval and synthesis once canonicalization exists; it should not be the authoritative ingestion-time linker. citeturn26search5turn26search10turn39view0turn39view1turn36view0turn36view1turn40search8turn0search19

## Terminology and what applies here

**Named entity recognition** identifies spans in unstructured text and assigns types such as person, organization, or location. Recent surveys still define NER primarily as extracting substrings that name real-world objects and classifying them into predefined categories. In your system, NER is the front door for Slack messages, email bodies, ticket titles, comments, and documents. It tells you that “Robin” is probably a person mention or, in weaker cases, an ambiguous named span. It does **not** tell you which Robin. citeturn29view2

**Entity linking** maps a mention in context to an entry in a knowledge base or canonical entity graph. The EL literature frames this as taking a textual mention such as “Michael Jordan” and linking it to the correct knowledge-graph entity given context. The standard modern EL pipeline is candidate generation followed by candidate ranking, with a NIL or unlinkable option when no gold entity exists. In your system, this is the step that decides whether “Robin” in “ask robin to move meeting” means Robin Scharf, an internal employee, a project name, or nobody you currently know. citeturn29view3turn39view1

**Entity resolution** identifies semantically equivalent entity records within one source or across sources. Rahm and Peukert explicitly define ER as identifying records that refer to the same real-world object, within one source or across multiple sources, and note that it is also called data deduplication, object matching, record linkage, or link discovery. In your system, ER is how `crm_contact:123`, `google_user:abc`, `slack_user:U123`, and `linear_user:xyz` become one canonical `Person`. It is also how company/account records, suppliers, services, documents, and repos cluster into canonical entities. citeturn29view1

**Record linkage** is the statistical or operational process of joining observations across datasets when reliable unique identifiers are absent. The BLS paper states this plainly and also describes the practical pipeline: preprocessing, indexing or blocking to create candidate pairs, pair comparison, and classification. In your setting, record linkage is best used for structured catalogs: contacts, companies, employees, vendors, service inventories, and account records. It is narrower than mention-level EL because it usually works over records rather than spans in free text. citeturn31view0turn30view0

What applies here is therefore a stacked view:

- **NER / mention detection** for free text from Slack, Gmail, comments, docs, transcripts, and ticket titles. citeturn29view2
- **Entity linking** for mapping those mentions to existing canonical entities, with NIL handling for unseen ones. citeturn29view3turn39view1
- **Record linkage / entity resolution** for consolidating structured source catalogs such as CRM people, account objects, workspace users, and service inventories. citeturn29view1turn31view0

The critical practical insight is that your system should never pretend these are the same task. It should share infrastructure, features, and evidence across them, but the labels, thresholds, and review workflows should differ. Structured catalog merges can tolerate a different feature space and different thresholds than one-off mention linking inside a Linear title.

## Recommended architecture

The right architecture is an **identity layer between ingestion and memory**. Store raw source objects first, resolve identities second, expose linked context third, and update peer memory last. Source-native IDs should be first-class keys because the major systems in your stack all expose stable object identifiers: Slack user objects expose `id` or `user_id`, Gmail messages expose immutable message IDs and thread IDs, Google Drive file APIs are organized around `fileId`, GitHub exposes `node_id` for direct node lookup, Linear exposes IDs for issues/users/teams and supports shorthand issue identifiers as well as UUIDs, and Google’s Directory API explicitly manages users and user aliases. citeturn27view1turn27view3turn28search0turn27view4turn27view5turn27view0

A practical production shape looks like this:

```text
[Source connectors]
  Slack | Linear | Gmail | Drive | CRM | GitHub | PM tools | Internal apps
        │
        ▼
[Raw ingestion journal]
  raw_objects
  raw_events
  source_refs(source, object_type, object_id)
  payload snapshots + ACL/provenance + timestamps
        │
        ├── exact deterministic linker
        ├── structured ER / record-linkage jobs
        ├── mention detector + text linker
        ▼
[Canonical identity layer]
  canonical_entities
  aliases
  source_record_links
  observed_mentions
  link_decisions
  merge_history
        │
        ├── relational edge tables in MVP
        └── optional graph DB in production
        ▼
[Context graph / retrieval layer]
  people, orgs, accounts, projects, tickets, docs, repos, services, events
  edges: actor / assignee / owner / mentions / relates_to / customer_of / etc.
        │
        ├── entity-centric retrieval
        ├── GraphRAG / query synthesis
        └── confidence-gated memory sync
        ▼
[Agent-facing memory]
  Honcho peers for durable entities only
  people / customers / projects / maybe teams
  no direct writes from ambiguous mentions
```

This architecture also aligns unusually well with Honcho’s model. Honcho is explicitly peer-centric; peers can represent users, agents, or any entity, messages are written to sessions, and those messages trigger background reasoning that updates peer representations. Honcho also supports importing external data through single-peer sessions. That makes it a good **memory endpoint**, but not a good place to decide identity. The identity decision needs to happen upstream. citeturn38view0turn38view1

A concrete relational schema for the identity layer can be small and still effective:

```sql
create table canonical_entities (
  entity_id uuid primary key,
  entity_type text not null,          -- person, org, project, ticket, repo, service, doc, event
  subtype text,                       -- employee, external_contact, customer_account, etc.
  canonical_name text,
  status text not null,               -- active, provisional, merged, retired, deleted
  confidence numeric,                 -- for provisional entities
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table source_records (
  source text not null,               -- slack, linear, crm, gmail, drive, github, ...
  object_type text not null,          -- user, issue, file, message, repo, ...
  object_id text not null,            -- native source ID
  entity_type_hint text,
  payload jsonb not null,
  observed_at timestamptz not null,
  primary key (source, object_type, object_id)
);

create table aliases (
  alias_id uuid primary key,
  entity_id uuid not null references canonical_entities(entity_id),
  alias_text text not null,
  alias_type text not null,           -- legal_name, display_name, nickname, email, domain, handle, url_slug
  source text,
  valid_from timestamptz,
  valid_to timestamptz,
  unique (entity_id, alias_text, alias_type)
);

create table observed_mentions (
  mention_id uuid primary key,
  source text not null,
  parent_source_type text not null,   -- message, issue, comment, doc, etc.
  parent_source_id text not null,
  span_text text not null,
  mention_type_hint text,             -- person?, org?, project?, event?
  context_window jsonb not null,
  observed_at timestamptz not null
);

create table link_decisions (
  link_id uuid primary key,
  mention_id uuid,                    -- nullable for record-linkage cases
  source text not null,
  target_entity_id uuid references canonical_entities(entity_id),
  decision text not null,             -- linked, nil, provisional, rejected, pending_review
  score numeric,
  model_family text,                  -- rules, fs, xgb, llm_rerank
  model_version text,
  explanation jsonb not null,
  evidence jsonb not null,
  created_at timestamptz not null
);

create table events (
  event_id uuid primary key,
  source text not null,
  object_type text not null,
  object_id text not null,
  event_type text not null,
  event_time timestamptz not null,
  raw_ref jsonb not null,
  unique (source, object_type, object_id, event_type, event_time)
);

create table event_entity_roles (
  event_id uuid not null references events(event_id),
  entity_id uuid not null references canonical_entities(entity_id),
  role text not null,                 -- actor, assignee, subject, customer, owner, mentioned, container
  confidence numeric not null,
  primary key (event_id, entity_id, role)
);
```

The important architectural rule is that **raw objects never disappear into memory directly**. They stay reconstructible. Every link decision stores evidence, scorer version, and confidence. Every memory write is derived and therefore retractable.

## Candidate generation and ranking

Candidate generation is where most of the quality battle is won. EL work consistently treats this as the step that reduces an otherwise huge search space into a shortlist of plausible senses, using combinations of surface-form matching, alias expansion, and prior probabilities. ER literature makes the same point in different language: candidate selection or blocking is the critical efficiency and quality gate that determines which comparisons happen at all. Modern work also shows that dense retrieval can improve recall, especially on short noisy text, but lookup dictionaries are still strong baselines when names and aliases are good. citeturn39view0turn34view3turn31view0turn35view0

For an enterprise workspace, the candidate catalog should be **typed** and **multi-view**. At minimum, build canonical catalogs for:

- **People**: CRM contacts, Slack users, Linear users, Google Workspace users, email correspondents, GitHub users, vendor contacts.
- **Organizations / accounts**: CRM companies, suppliers, customers, vendors, internal departments, client subsidiaries.
- **Projects / workstreams**: Linear projects, internal PM projects, customer rollout names, named initiatives.
- **Artifacts**: Linear issues, GitHub repos, documents, meetings/events, tickets, threads, services.
- **Containers**: Slack channels, email threads, Linear teams, shared drives, folders.

Every catalog item should carry source-native references, aliases, ownership or membership edges, recency signals, and a serialized “profile” for vector retrieval. The “profile” is not just display text; it should include short facts such as title, description, owners, nearby entities, domains, customer/account association, recent activity, and source handles.

In practice, candidate generation should run in this order:

1. **Direct source-ID linking**. If the source object already contains an explicit ID, URL, email address, or resolvable mention format, use it. Slack user IDs, GitHub node IDs, Drive `fileId`, Gmail message/thread IDs, Linear IDs, and Google Directory users/aliases are high-precision anchors. citeturn27view1turn27view3turn27view4turn28search0turn27view5turn27view0

2. **Exact alias lookup**. Match normalized full names, primary emails, alternate emails, handles, repo full names, service names, customer domains, and known nicknames.

3. **Fuzzy lexical lookup**. Use lowercasing, accent folding, token sort, trigrams, edit distance, phonetic keys when relevant, and field-specific normalizers. PostgreSQL’s built-in full-text search and `pg_trgm` are enough for an MVP candidate service. citeturn26search5turn26search10

4. **Embedding retrieval**. For short or ambiguous spans, embed the mention-plus-context and retrieve the nearest entity profiles. This is especially helpful when the surface string is indirect, abbreviated, or misspelled. Dense-retrieval EL work on short social text found that a hybrid of lookup and dense retrieval materially improved recall. citeturn35view0

5. **Graph-neighborhood expansion**. Once a few candidates exist, expand locally using neighboring entities from the same thread, channel, meeting, customer account, project, or recent counterparties. Blocking and meta-blocking work in ER also supports the intuition that co-occurrence patterns and shared blocks are powerful candidate signals. citeturn34view2turn36view0turn36view1

6. **Temporal filtering**. Downweight stale projects, archived tickets, deleted users, and inactive aliases. Gmail’s `internalDate` is particularly useful because Google documents that it is more reliable than the raw `Date` header for normal SMTP-received email. citeturn27view3

A candidate-ranking stack should then use three tiers.

The first tier is **deterministic hard rules**. If a mention resolves via explicit source ID, exact email, direct URL, unique known alias in the local scope, or an exact source-native mention format, do not send it to a probabilistic model. In enterprise systems, these high-precision cases are abundant and should dominate coverage.

The second tier is a **probabilistic linker**. For structured record linkage, the Fellegi–Sunter family remains foundational, and modern tooling such as Splink is effective when you want explainable comparisons over names, emails, companies, addresses, or domains. For text-mention linking, a lightweight logistic regression or boosted-tree model works well over features such as alias match quality, mention-type compatibility, email-domain overlap, customer/project consistency, neighbor overlap, recent communication priors, and temporal distance. Record-linkage literature explicitly describes candidate generation, comparison, and classification stages, and modern ER still treats the task as a scored decision under uncertainty. citeturn30view0turn31view0turn29view1turn23search0

The third tier is **LLM or cross-encoder reranking over a bounded top-k only**. Neural EL surveys note that a ranking formulation is the standard architecture and that BERT-based cross-encoders over mention context plus candidate description can be very effective, but also computationally expensive. In your environment, the safe use of an LLM is not “Who is Robin?” with no constraints; it is “Here are 5 typed candidates plus NIL. Return one candidate ID or NIL, with a rationale grounded in the supplied evidence.” That design sharply reduces hallucinated entity creation. It also keeps the authoritative entity store free from unconstrained generations. citeturn39view1

Confidence thresholds should be asymmetric. Because false positive links contaminate downstream memory, the automatic-write threshold should be high. A practical pattern is:

- **Auto-link and allow memory writes** only above a high calibrated threshold.
- **Link provisionally in the graph but suppress peer-memory updates** in the middle band.
- **Emit NIL or pending-review** below the review threshold.

Always rank against a **NIL or no-link option**. EL literature explicitly treats unlinkable mentions as part of the architecture, and NIL-aware work exists because “forcing” a link is worse than abstaining when memory quality matters. citeturn39view1turn18search2turn18search3

## New entities, graph schema, and memory routing

You should create a **provisional entity** whenever a mention or record is important enough to preserve, but no candidate clears the auto-link threshold. Good triggers are repeated mention recurrence, the presence of a stable external identifier in a source, or repeated co-occurrence with the same neighborhood. A provisional entity should not be a second-class citizen; it should have its own canonical ID, status=`provisional`, aliases, source evidence, and link history. Later, it can merge into a durable canonical entity while retaining provenance. This is much safer than either dropping the evidence or forcing an incorrect merge. The merge itself should produce a durable `MERGED_INTO` history, not overwrite history in place. citeturn29view1turn31view0

A useful graph schema is entity-centric rather than document-centric:

```text
(:Person {employee/external flags})
(:Org)
(:CustomerAccount)
(:Project)
(:Ticket)
(:Document)
(:Repo)
(:Service)
(:Meeting)
(:Channel)
(:Thread)
(:Alias)
(:SourceRecord)
(:Event)

(:SourceRecord)-[:RESOLVES_TO {score, method, version}]->(:Person|:Org|...)
(:Entity)-[:HAS_ALIAS]->(:Alias)
(:Person)-[:WORKS_AT]->(:Org)
(:CustomerAccount)-[:BELONGS_TO]->(:Org)
(:Project)-[:FOR_CUSTOMER]->(:CustomerAccount)
(:Ticket)-[:IN_PROJECT]->(:Project)
(:Event)-[:ACTOR]->(:Person)
(:Event)-[:ASSIGNEE]->(:Person)
(:Event)-[:SUBJECT]->(:Person|:Org|:Project|:Meeting)
(:Event)-[:ABOUT]->(:Ticket|:Document|:Repo|:Service)
(:Event)-[:IN_CONTAINER]->(:Channel|:Thread|:Project)
(:Event)-[:MENTIONS]->(:Entity)
(:Document)-[:OWNED_BY]->(:Person|:Org)
(:Repo)-[:OWNED_BY]->(:Org|:Person)
(:Message)-[:IN_THREAD]->(:Thread)
```

Neo4j is useful here because the graph is not just storage; it can contribute to disambiguation. Neo4j’s Graph Data Science library includes node similarity, and both research and practice show that structured graph information improves entity disambiguation. Work on graph embeddings and GNN-based disambiguation found that graph-structured knowledge materially improves candidate ranking relative to text-only approaches. That maps directly onto your environment: if Olivia, Robin Scharf, Customer X, a sales thread, and a project all sit in the same recent neighborhood, that should affect the score. citeturn13search0turn36view0turn36view1

GraphRAG is relevant, but with a clear boundary. Microsoft’s GraphRAG work builds graphs, community structure, and summaries for query-focused retrieval and synthesis. Neo4j’s own GraphRAG package positions itself as a first-party package for graph-based retrieval patterns. For your problem, that is valuable **after** canonical entities and links exist, especially for questions like “what is going on with customer X?” or “what is Robin waiting on?” where the answer spans tickets, emails, meetings, documents, and repos. It is not the best authoritative ingestion-time linker because that layer must remain auditable, confidence-scored, and reversible. citeturn0search19turn40search8turn40search5

The cleanest memory-routing rule is: **store the raw event once, then attach roles**. Do not mirror the full raw payload into ten peers by default. Instead, create one event and assign roles such as actor, assignee, subject, mentioned entity, customer, and container. Then decide which entities deserve a derived memory update.

A good routing policy is:

- **Actor** gets the event when it reflects actions or commitments they own.
- **Assignee / owner** gets the event when it changes their queue or waiting state.
- **Subject entity** gets the event when the event changes that entity’s persistent state.
- **Customer / project / container** gets the event when it materially advances the status of that account or project.
- **Mentioned-only entities** usually do **not** get a memory write unless the mention is high-confidence and salient.

For Honcho specifically, I would sync only **durable target peers** such as people, customers/accounts, projects, and perhaps teams. I would not make every ticket, message, or document a peer unless the application genuinely queries them as first-class long-lived entities. Honcho is excellent at building cross-session representations of peers, but that is exactly why ambiguous writes are dangerous. citeturn38view0turn38view1

For the example Linear ticket titled **“ask robin to move meeting”**, created by Olivia and assigned to Olivia, the system should behave like this:

| Decision point | Recommendation |
|---|---|
| Olivia | Link exactly from Linear assignee and creator IDs; this is high precision. citeturn27view5 |
| Ticket object | Store as a single raw event and ticket/artifact node with provenance from Linear. |
| “Robin” mention | Create a typed mention `PERSON?` plus a candidate set from people catalogs first; do not compete against project/company entities unless the type classifier is uncertain. citeturn29view2turn39view0 |
| If only evidence is the title plus Olivia/team metadata | Keep Robin unresolved or provisional. Route the event to Olivia and to the Linear team/project container, but do **not** write it into Robin Scharf’s peer memory yet. |
| If nearby evidence shows recent emails with `robin.scharf@customer.com`, the issue belongs to Customer X’s project, and Robin Scharf is an active customer contact in that neighborhood | Link Robin Scharf above threshold, attach the event to Olivia, Robin Scharf, Customer X, and the project, but still store the raw event once and derive per-peer memory views. |
| Meeting | Treat as an artifact or event mention, not a person. If a calendar object or thread is found, link that separately. If not, leave as an unlinked activity object. |

The fallback should almost never be “guess the customer contact.” The safer fallback is the **container**: the Linear team, project, or ticket itself.

## Evaluation and operational controls

You should evaluate this system at **three distinct levels**.

The first is **candidate-generation coverage**. Measure Recall@k per entity type and per source. If the correct entity is not in the top-k set, no ranker can save you. EL and ER literature both place strong emphasis on candidate generation because it shapes both efficiency and ceiling performance. citeturn39view0turn34view3

The second is **link-decision quality**. For mention-level EL, use precision, recall, F1, top-1 accuracy on non-NIL cases, and NIL F1 or unlinkable accuracy. Neural EL surveys explicitly describe unlinkable mentions as part of the architecture, so NIL handling needs separate measurement. For structured record linkage, measure pairwise precision and recall over predicted links. citeturn39view1turn29view3turn31view0

The third is **merge and clustering quality**. Once you start consolidating multiple source records into one canonical entity, pairwise link metrics are no longer enough. Use cluster metrics such as B-cubed alongside pairwise metrics to catch over-merging and under-merging. Recent work on evaluating record linkage also emphasizes consistent treatment of pairwise vs. cluster-level outcomes. citeturn16search8turn15search11

A gold dataset for company/workspace data should be **stratified**, not random. Include at least these slices:

- common first names that collide across internal and external people,
- customers vs. employees with the same name,
- renamed companies or projects,
- aliases and nicknames,
- archived vs. active entities,
- multilingual or misspelled mentions,
- cross-source cases where one entity appears in Slack, Gmail, CRM, and Linear,
- “no entity exists” cases.

Use double-blind annotation with adjudication for disagreements. BLS’s record-linkage writeup explicitly notes that gold-standard labels are expensive and ideally double-coded with adjudication, which is good advice here too. citeturn31view0

Operationally, the system should be **incremental, idempotent, auditable, and retractable**.

Incremental ingestion means every webhook or sync job writes source objects and events as append-only records, keyed by source-native IDs. Slack exposes unique event IDs through its Events API, Gmail messages have immutable message IDs, and other sources expose stable object IDs; these should become your idempotency keys or part of them. citeturn25search0turn27view3turn27view5

Auditability means every link stores the candidate set, feature values, scorer version, explanation, and raw evidence snapshot. When a human corrects a link, do not silently mutate the past. Instead, append a superseding link decision and re-derive affected memories or summaries. Because Honcho updates peer representations from stored messages, corrections should trigger peer-summary repair as well as graph-edge repair. citeturn38view0turn38view1

Versioning matters. Matching rules, alias dictionaries, and learned models should all have explicit versions recorded with each decision. This lets you answer questions like “Why was Robin linked to Robin Scharf last month but not today?” and lets you backtest a new matcher over old evidence without rewriting history.

Deletion and retention need a derived-data policy. If a source record is deleted or falls out of retention scope, the system should be able to tombstone the raw record, invalidate derived edges, and retract or regenerate affected memory summaries. The more derived your memory system becomes, the more important it is to keep the upstream evidence graph reconstructible.

## Tooling choices, risks, and roadmap

The stack decision should follow the architecture, not reverse it. A concise practical comparison is below. The maturity labels are my operational assessment based on project age, documentation, release cadence, and ecosystem usage signals as of June 2026; where I did **not** independently recheck a license in this pass, I say so explicitly.

| Tool | License | Maturity | Best fit |
|---|---|---|---|
| **Neo4j** | Community Edition GPLv3; Enterprise commercial. citeturn41search12turn41search4 | Mature | Best when graph neighborhoods, multi-hop traversals, merge lineage, and graph algorithms are central. Graph Data Science and first-party GraphRAG support make it strong for entity-centric retrieval after linking. citeturn13search0turn40search8turn40search5 |
| **PostgreSQL** | PostgreSQL License. citeturn43search0turn43search8 | Mature | Best default system of record for raw ingestion, canonical tables, audit logs, and MVP candidate lookup via full-text plus `pg_trgm`. citeturn26search5turn26search10 |
| **Splink** | MIT. citeturn23search0 | Mature niche | Excellent for explainable probabilistic linkage of structured records such as contacts, companies, and account objects. Good for feature inspection and threshold tuning. |
| **Zingg** | AGPLv3. citeturn40search1turn40search4 | Maturing | Stronger fit when you need Spark-scale entity resolution, clustering, and active-labeling workflows over very large structured catalogs. Recent releases show active maintenance. citeturn40search10 |
| **dedupe** | MIT. citeturn40search0turn40search3 | Mature niche | Very practical Python library for structured fuzzy matching, entity resolution, and active learning, especially for internal experiments. citeturn40search12 |
| **spaCy** | MIT. citeturn42search0turn42search3 | Mature | Best general-purpose NLP pipeline for mention detection, custom NER, lightweight text processing, and deterministic pipeline composition. |
| **GLiNER** | License not independently rechecked in this pass | Newer / promising | Good option when you want flexible zero-/few-shot entity extraction and lightweight typed spans without fully training a custom NER model. Use it for mention detection, not as the final linker. citeturn29view2 |
| **Presidio** | MIT. citeturn42search1turn42search4 | Mature specialized | Use before indexing for PII detection, redaction, and governance. It is not your core linker, but it is valuable for privacy and compliance boundaries. citeturn42search7 |
| **LanceDB** | Apache 2.0. citeturn42search2turn42search14 | Maturing | Good embedded vector store for entity-profile retrieval and local-first candidate search; useful when you want vector search without operating a distributed search cluster. |
| **OpenSearch** | License not independently rechecked in this pass | Mature | Good when you need distributed hybrid search across very large corpora or already run it in-house; more operational overhead than PostgreSQL for an MVP. |
| **DuckDB** | License not independently rechecked in this pass | Mature analytic engine | Best for offline labeling, feature generation, evaluation, and local analytics. Not usually the primary online identity store. |
| **NetworkX** | License not independently rechecked in this pass | Mature prototyping library | Best for offline graph experiments, evaluation, and algorithm prototyping. Not an operational serving database. |

Two additional tooling notes matter. First, Honcho is a strong **agent-facing memory endpoint** because it is peer-centric, background-reasoning-based, and supports importing external data into peer/session/message structures. Second, LLM-based rerankers are useful, but only after deterministic and statistical narrowing. They should choose from candidate IDs or NIL, not invent entities. citeturn38view0turn38view1turn39view1

The biggest risks and failure modes are predictable.

The most dangerous one is the **false positive link that looks plausible**. These are worse than misses because they contaminate memory, graph features, downstream retrieval, and future disambiguation. Honcho’s background peer reasoning makes that especially important. citeturn38view0turn38view1

The second is **over-merging across roles**: employee vs. customer contact, parent company vs. customer account, project name vs. company name, repo vs. service name. Typed candidate generation and type-first ranking are the best defense. citeturn29view2turn39view0

The third is **authority drift**: aliases change, projects get renamed, people leave, and organizations reorganize. Your entity model therefore needs alias validity windows, status flags, and versioned link logic.

The fourth is **review starvation**. If the system has an abstain path but no review queue, ambiguous but important entities accumulate forever in limbo. Active-learning tools such as dedupe or Zingg become more valuable as ambiguity volume grows. citeturn40search0turn40search1

A practical implementation roadmap is:

**MVP for an internal experiment**

Use PostgreSQL for raw events, canonical entities, aliases, link decisions, and edge tables. Build deterministic candidate generation on source-native IDs, emails, handles, domains, and curated aliases. Add `pg_trgm` plus full-text search for fuzzy candidate lookup. Run spaCy or GLiNER for mention extraction. Use a simple probabilistic ranker for ambiguous person/company linking. Keep a human-review queue for the middle confidence band. Sync only high-confidence people, customers, and projects into Honcho. No graph database yet. citeturn26search5turn26search10turn42search0turn38view0

**Next version for production**

Add structured ER jobs for contacts and accounts using Splink, dedupe, or Zingg depending on scale and governance needs. Add vector retrieval for entity profiles and dense candidate recall. Introduce a bounded LLM or cross-encoder reranker for top-k ambiguous cases. Add retrieval views for “customer status” and “person waiting-on” queries. Only then consider Neo4j if relationship-heavy reasoning becomes central. citeturn23search0turn40search0turn40search1turn35view0turn39view1

**When a graph database is justified**

Use Neo4j when you repeatedly need multi-hop neighborhood reasoning such as “show all active blockers for customer X across tickets, docs, meetings, and owners,” when link quality clearly improves from graph-neighborhood features, or when auditability of merges and same-as lineage becomes too awkward in relational edge tables. If your queries remain mostly person/account/project joins and your entity count is still moderate, a relational identity layer is simpler and safer. citeturn13search0turn36view0turn41search12

**Where LLMs belong**

Introduce them late. They are best for summarizing already linked evidence and for reranking small, typed candidate sets. They should not be your first linker, your canonical registry, or your merge authority. citeturn39view1

### Open questions and limitations

A few tooling-license details were not independently rechecked from primary project sources in this pass, specifically for GLiNER, OpenSearch, DuckDB, and NetworkX. I therefore avoided over-claiming on those licenses and limited the stronger tool recommendations to the projects whose official docs or repositories I verified directly. The architecture recommendation itself is high confidence: deterministic identity first, probabilistic scoring second, bounded LLM reranking third, graph-enhanced retrieval after canonicalization, and confidence-gated memory writes last.
