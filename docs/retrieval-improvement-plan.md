# Retrieval Improvement Plan

**Goal:** Make `fourok retrieve` return agent-ready governed context, not search-result previews.

**Architecture:** Keep retrieval source-agnostic: rank atomic evidence first, then assemble context through canonical objects and provenance. Final output is limited by a token budget, not a fixed number of items.

**References reviewed:**
- `tobi/qmd` commit `e428df7`: hybrid BM25/vector/HyDE search, RRF fusion, doc IDs, line-aware `get`, hierarchical context, MCP instructions.
- Graphiti/Zep: temporal context graphs with entities, facts, episodes/provenance, hybrid semantic/keyword/graph traversal.
- Mem0: entity linking, multi-signal retrieval, temporal reasoning, token-efficient memory retrieval.

---

## Current gap

Live local retrieval is working, but output quality is too preview-like:

- results are capped by item count instead of context budget;
- snippets are short and often look like ticket metadata;
- issue descriptions and comments exist in storage but are not assembled into useful context packs;
- Linear comments and issues are separate source records, but retrieval should not hard-code Linear thread logic;
- canonical objects currently mirror source records too closely, so source-agnostic expansion needs both immediate fallback behavior and later graph enrichment;
- temporal queries such as “What changed this week?” rank old lexical matches because time intent is not handled.

---

## Target retrieval flow

```text
query
  -> query planning
       lexical terms, semantic query, temporal intent, entity/name hints
  -> candidate retrieval
       keyword, vector, entity/object match, temporal/activity signal
  -> fusion/rerank
       RRF-style multi-signal fusion, optional reranker later
  -> canonical expansion
       map source hits to object_refs, direct linked canonical objects, provenance source records
  -> token-budget packer
       default 2k tokens, add context packs in rank order until full
  -> rendered agent context
       citeable source/object refs plus useful evidence text
```

---

## Implementation stages

### Stage 1 — Token-budgeted evidence output

**Objective:** Replace the final fixed 5-item cap with a 2k-token budget.

**Files:**
- Modify: `src/fourok/retrieval/augmentation.py`
- Modify: `src/fourok/governance/context.py`
- Modify: `src/fourok/retrieval/api.py`
- Modify: `src/fourok/retrieval/clients/cli.py`
- Modify: `src/fourok/retrieval/cli.py`
- Test: `tests/retrieval/test_retrieve_cli.py`
- Test: `tests/test_retrieval_agent_experience.py`

**Acceptance:**
- `fourok retrieve` has default token budget of 2000 estimated tokens.
- Results are added in rank order until adding the next card would exceed the budget.
- Internal `candidate_limit` remains for performance; output selection is not item-count based.
- JSON includes enough budget metadata for tests/operators to see selected vs candidate behavior.

### Stage 2 — Better evidence rendering

**Objective:** Make each selected card contain useful answerable context.

**Acceptance:**
- Evidence preserves paragraph boundaries where practical.
- Duplicated issue ID/title prefixes are removed.
- Long records get larger excerpts than today when budget allows.
- Metadata-only lines stay minimal: source refs, relevance, date, evidence.

### Stage 3 — Source-agnostic canonical expansion

**Objective:** Expand high-ranked hits through canonical objects and direct links, not source-specific Linear rules.

**Initial expansion order:**
1. ranked source hit;
2. canonical object(s) linked to the source hit;
3. source refs on those canonical objects;
4. directly linked canonical neighbors from `entity_links`;
5. transitional fallback via `thread_ref` siblings until canonical graph is richer.

**Acceptance:**
- Context packs are grouped by object/canonical ref when available.
- Evidence is deduplicated by source ref and object ref.
- Linear issue/comment assembly works as an outcome of canonical/provenance expansion, not as a Linear-only core abstraction.

### Stage 4 — Temporal retrieval

**Objective:** Make update-oriented queries use time.

**Acceptance:**
- Detect query phrases such as “this week”, “today”, “recent”, “latest”, “changed”, “updates”.
- Rank/filter using `updated_at` and `occurred_at` alongside relevance.
- Only restore examples like `fourok retrieve "What changed this week?"` once this is reliable.

### Stage 5 — Evaluation case set

**Objective:** Prevent regressions with observable retrieval-quality tests.

**Queries:**
- `What did Simon say about Leonard Joel outreach?`
- `What changed this week?`
- `domain access website`
- `refund simon`
- `current fourok priorities`

**Acceptance:**
- useful evidence text present;
- cited source refs present;
- canonical/direct-link context included where available;
- output within token budget;
- no `permission_refs:` in rendered context;
- no metadata-only cards when underlying source text exists.

### Stage 6 — Honcho memory fusion spike

**Objective:** Add agent long-term memory as a small, optional section fused into
the retrieval response after governed evidence retrieval, without making Honcho
the source of truth or reviving the old source-sync implementation.

**Lowest-effort shape:** keep `fourok retrieve` source-record-first, then append a
short `Memory` section populated by a Honcho search for the same user turn. The
section should be capped separately from evidence, cite that it is memory rather
than source evidence, and never satisfy evidence requirements by itself.

**Open questions to investigate:**
- If Honcho is used only through MCP, it can answer/search only the history that
  the host client or Honcho integration has already written. MCP tools do not
  automatically receive full session history; the agent host must either write
  turns to Honcho or pass enough current-session context when calling the tool.
- The easiest fill path is agent-conversation continuity: let the agent runtime's
  Honcho integration record user/AI turns and retrieve peer/session/workspace
  memory at query time.
- Source-system data should not be bulk-filled through Honcho first. If we later
  add structured external events, write only deliberate high-salience memory
  events derived from governed source records, with source refs in metadata and
  idempotent write receipts.

**Acceptance for the spike:**
- JSON output includes an optional `memory` object with status, query, source
  (`honcho`), bounded items, and limitations.
- Block output includes at most a short `Memory` section after source evidence.
- Missing/unavailable Honcho is a visible limitation, not a retrieval failure.
- Tests prove that evidence retrieval still passes when memory is unavailable and
  that memory text cannot replace source-backed evidence.

---

## Borrowed best practices

Adopt now:
- candidate search separate from context packing;
- stable citeable refs for every evidence item;
- token-budgeted output;
- RRF-style multi-signal fusion;
- explicit query intent/type handling over time.

Borrow later:
- HyDE query expansion;
- local reranking model;
- dynamic MCP instructions that describe index health and searchable sources;
- line/range fetch tools for source records if agents need follow-up reads.

Avoid:
- file/path-centric assumptions from qmd;
- requiring normal users to manually call a second `get` command after `retrieve`;
- source-specific Linear thread assembly as the core model;
- adding new public CLI surface before the default `retrieve` output is good.
