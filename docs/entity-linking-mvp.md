# Entity Linking MVP

Goal: deterministically identify enough employee entities for the first Honcho
experiment, then test CRM/company mention linking as evidence metadata before
writing durable non-employee Honcho peers.

This MVP is for the internal, non-governed Honcho experiment.

- Iteration 1 is employee-peer focused.
- Iteration 2 adds CRM/company candidate linking, not default CRM company peer
  writes.

Prefer deterministic employee attribution and source/container fallback over
guessing customer/company subjects. Preserve routing metadata so false positives
can be reviewed and repaired.

## Problem

Workspace events often mention the real subject only in text.

Example:

```text
Linear issue title: "ask robin to move meeting"
created by: Olivia
assigned to: Olivia
```

In Iteration 1, the peer is Olivia because she is the deterministic employee
actor/assignee. In Iteration 2, the system may detect Robin or Robin's company
as candidate linked entities, but those candidates should stay metadata unless
the link is high confidence and the event is salient enough for a deliberate
derived memory write. Honcho peer choice determines what memory is built, so
ambiguous subject guesses must not be written directly into peer memory.

## Scope

Iteration 1 source catalogs:

- Twenty workspace members
- Slack users, identity catalog only
- Linear users
- Linear teams
- Linear projects

Iteration 1 event sources:

- Linear issues/comments/status changes

Iteration 2 additional catalogs:

- Twenty people
- Twenty companies

Later catalogs:

- Slack channels
- GOG entities after preflight identifies stable object types

## Entity Model

Use two layers.

Canonical entities:

```text
employee:email:<normalized-email>
linear:team:<id>
linear:project:<id>
source:<source-name>
```

Source identities:

```text
twenty:workspaceMember:<id>
slack:user:<id>
linear:user:<id>
```

Employees are the only automatically merged entity type in the MVP.

Rule:

```text
same normalized email address -> same canonical employee
```

Do not automatically merge employees by first name, full name, username, handle,
avatar, or fuzzy similarity.

## OpenClaw Peer Compatibility

OpenClaw will be the base agent connected to Honcho and will communicate with
employees through Slack. Therefore imported Linear data must write to the same
Honcho employee peers that OpenClaw's Honcho integration creates for Slack
employees.

Honcho's unified memory guide documents Slack-style peers as:

```text
slack_<slack_user_id>
```

Iteration 1 must therefore:

- import the Slack user directory for identity mapping only
- match Slack users to Twenty workspace members and Linear users by normalized
  email
- store the OpenClaw/Honcho peer id on the canonical employee
- write Linear-derived employee messages to that OpenClaw-compatible peer id
- avoid creating parallel `employee:email:<email>` Honcho peers when a Slack
  peer id exists
- report employees without Slack peer mapping as unresolved for OpenClaw peer
  compatibility

Internal state may still use `employee:email:<normalized-email>` as the stable
canonical entity ref. Honcho writes should use the resolved `honcho_peer_id`.

Iteration 2 catalogs add:

```text
twenty:company:<id>
twenty:person:<id>
```

CRM people are not Honcho subject peers. When Iteration 2 matches a Twenty
person, keep the person and linked `twenty:company:<id>` as candidate metadata.
Do not route to the company by default. A company Honcho peer write is a later
experiment that requires high confidence, salience, and an explicit memory-write
policy. If the person has no linked company, keep the candidate unresolved or
provisional.

## Data Shapes

Canonical entity:

```json
{
  "entity_ref": "employee:email:olivia@example.com",
  "entity_type": "employee",
  "display_name": "Olivia Smith",
  "primary_email": "olivia@example.com",
  "honcho_peer_id": "slack_U123456",
  "source_identities": [
    "twenty:workspaceMember:abc",
    "slack:user:U123456",
    "linear:user:def"
  ],
  "aliases": ["Olivia Smith", "Olivia"]
}
```

Source identity:

```json
{
  "source_identity_ref": "linear:user:def",
  "source": "linear",
  "source_type": "user",
  "source_id": "def",
  "display_name": "Olivia Smith",
  "email": "olivia@example.com",
  "canonical_entity_ref": "employee:email:olivia@example.com",
  "honcho_peer_id": "slack_U123456"
}
```

Entity candidate:

```json
{
  "entity_ref": "employee:email:olivia@example.com",
  "entity_type": "employee",
  "display_name": "Olivia Smith",
  "source": "linear",
  "matched_text": "linear-assignee",
  "match_kind": "source_native_user_email",
  "confidence": "high",
  "reason": "Linear assignee matched Twenty workspace member by email"
}
```

Routing decision:

```json
{
  "source_ref": "linear:issue:ABC-123",
  "primary_peer": "slack_U123456",
  "employee_peer": "employee:email:olivia@example.com",
  "honcho_peer_id": "slack_U123456",
  "aggregate_fallback_peer": "linear:team:ops",
  "actor_peers": ["employee:email:olivia@example.com"],
  "assignee_peers": ["employee:email:olivia@example.com"],
  "candidate_entities": ["employee:email:olivia@example.com"],
  "confidence": "medium",
  "decision_rule": "linear_assignee_employee_match"
}
```

## Candidate Generation

Generate candidates from structured source links first:

- Linear creator, assignee, team, project
- Twenty workspace member
- Slack user by email, for OpenClaw/Honcho peer id

Iteration 1 does not search text for CRM entities. It routes by deterministic
source identities:

- assignee employee
- creator employee
- commenter employee
- aggregate fallback

Employee routing requires a resolved `honcho_peer_id` compatible with OpenClaw.
If a Linear/Twenty employee has no Slack/OpenClaw peer mapping, route to
aggregate fallback and record the unresolved employee mapping.

Iteration 2 searches catalogs from text:

- issue title
- issue description
- comment body

Iteration 2 Twenty search should query:

- people
- companies
- opportunities later, if needed

Use Twenty filters/search as a candidate source, not as the final linker.

## Ranking Rules

Automatic high confidence:

- exact email match
- source-native object id
- Linear user matched to employee by normalized email

Iteration 2 high confidence:

- exact full-name match with one candidate
- exact company/domain match with one candidate
- CRM person match with linked company and supporting local context

Iteration 2 medium confidence:

- unique first-name match within one candidate category
- exact alias match with one candidate
- search result with strong surrounding context, such as company and person
  both mentioned

Ambiguous:

- multiple first-name matches
- match across both employee and CRM person with no context
- fuzzy match only
- LLM-suggested match without deterministic candidates

Ambiguous records should not be written to guessed CRM/company peers. Keep the
candidate set in metadata, and route the Honcho write to the deterministic
employee actor/assignee or to a source/team/project container. Preserve
candidates in metadata for review.

Confidence gates:

- high: link may be used for retrieval metadata and, if salient, an explicit
  derived Honcho peer write experiment
- medium: provisional link only; no CRM/company Honcho peer write
- low/ambiguous: candidate metadata only, or `none`

## LLM Use

LLMs are allowed only as bounded rerankers after deterministic candidate
generation.

Allowed:

```text
Given this text and these 5 candidates, rank the most likely entity.
```

Not allowed:

```text
Invent the entity this text is about.
```

LLM output must include:

- selected candidate id or `none`
- linked company id when the selected candidate is a CRM person with a linked
  company
- confidence
- short reason

LLM reranking is out of scope for Iteration 1. In Iteration 2, low-confidence or
conflicting LLM output stays provisional or unresolved. Do not use LLM output as
the sole authority for CRM/company Honcho peer writes.

## Honcho Routing

Use these roles:

- subject peer: what Honcho should learn about
- actor peer: who performed the action
- assignee peer: who owns the task
- employee fallback peer: deterministic employee when subject is unknown
- aggregate fallback peer: source/team/channel/project bucket when no employee
  exists

Iteration 1 routing:

- write to assignee employee when available
- else write to creator/commenter employee when available
- else write to aggregate fallback peer
- keep all actors/assignees in message text and metadata
- do not search CRM people/companies for peer selection

Iteration 2 routing:

- keep CRM people/companies as candidate metadata by default
- write to a CRM/company subject peer only for a separate high-confidence,
  high-salience derived-memory experiment
- when the selected subject is a CRM person, keep the linked CRM company in
  metadata; do not create CRM person peers
- do not create CRM person peers for Honcho writes in the MVP
- keep actors/assignees in message text and metadata
- if the subject is ambiguous but actor or assignee is deterministic, write to
  the employee fallback peer for actor attribution, not as a subject claim
- if no deterministic employee fallback exists, write to aggregate fallback peer
- do not mirror into every involved peer by default

Internal employee refs:

```text
employee:email:<normalized-email>
```

Honcho employee peer ids:

```text
slack_<slack_user_id>
```

Aggregate fallback peers:

```text
linear:team:<id>
linear:project:<id>
slack:channel:<id>
twenty:workspace
source:gog
source:<source-name>
```

Example Honcho message:

```json
{
  "peer": "slack_U123456",
  "session": "slack_U123456:linear:2026-06",
  "text": "Linear issue ABC-123: Olivia created and assigned herself a task titled 'ask Robin to move meeting'.",
  "metadata": {
    "source": "linear",
    "source_ref": "linear:issue:ABC-123",
    "source_url": "https://linear.app/...",
    "actors": ["employee:email:olivia@example.com"],
    "assignees": ["employee:email:olivia@example.com"],
    "employee_peer": "employee:email:olivia@example.com",
    "honcho_peer_id": "slack_U123456",
    "aggregate_fallback_peer": "linear:team:ops",
    "routing_confidence": "high"
  }
}
```

## Source Connections

The first implementation slice covers Linear plus Twenty and Slack employee
identity only.

Credential source:

- load `LINEAR_API_KEY` from external secret manager
- load `TWENTY_API_KEY` from external secret manager
- load `SLACK_BOT_TOKEN` from external secret manager for identity lookup only
- never print token values

Twenty preflight:

- verify API authentication
- inspect available object metadata
- verify `workspaceMembers` are queryable
- report only object names, counts, and redacted availability

Twenty catalog import for Iteration 1:

- import a bounded page of workspace members
- build source identities for workspace members
- build canonical employee entities by normalized `userEmail`

Slack identity import for Iteration 1:

- import Slack users for identity mapping only
- store Slack user id, normalized email, display name, deleted/bot status when
  available
- map Slack users to canonical employees by normalized email only
- derive `honcho_peer_id` using the OpenClaw-compatible Slack peer id format
- do not ingest Slack messages in Iteration 1

Twenty catalog import for Iteration 2:

- import a bounded page of people
- import a bounded page of companies
- build CRM company candidate entities
- build CRM person source identities and link them to CRM companies when
  `companyId` is available
- store source ids, display names, emails/domains when available, and source
  URLs or object refs when available

Twenty candidate search for Iteration 2:

- query people, companies, and workspace members
- support exact full-name, first-name, email, domain, and `searchVector` based
  candidates where available
- preserve matched people with `companyId` as linked company candidates
- return normalized `EntityCandidate` records
- do not return raw secret or unrelated record payloads

Linear preflight:

- verify API authentication
- verify viewer/workspace access
- verify users, teams, projects, and issues can be queried
- report only workspace/team names, counts, and redacted availability

Linear catalog import:

- import a bounded page of users
- import teams and projects needed by sampled issues
- build source identities for users
- match Linear users to canonical employees by normalized email only
- attach the employee's resolved OpenClaw/Honcho peer id when a Slack match
  exists

Linear event import:

- import a bounded page of recent issues
- include title, description, creator, assignee, team, project, status,
  timestamps, URL, and source id
- include a bounded set of comments or timeline events when feasible
- normalize each issue/comment/status change into an event record
- route to employee peer or aggregate fallback according to Iteration 1 rules
- use the employee's OpenClaw/Honcho peer id for Honcho writes
- write normalized messages into Honcho

Iteration 2 adds CRM subject routing by searching Twenty from title,
description, and comment text as candidate metadata only. CRM/company Honcho
peer writes require a later explicit experiment and high-confidence gates.

Idempotency:

- source refs must be stable
- repeated imports must update or skip the same source ref, not create duplicate
  Honcho messages
- routing decisions must keep the rule version used for later review

Day 2 import:

- refresh Twenty and Linear catalogs before importing new Linear events
- refresh Slack user identity mappings before importing new Linear events
- upsert entities and source identities by stable source identity refs
- retain canonical employees across runs
- update display names, aliases, company links, emails, domains, and source
  timestamps when source catalog data changes
- in Iteration 2, if a CRM person changes company, future routing uses the new
  company
- existing Honcho messages and routing decisions are not rewritten during normal
  sync
- re-routing old records requires an explicit repair/reindex command
- import Linear events using stored source checkpoints and source `updatedAt`
  fields or cursors where available
- query deltas with a small overlap window and de-duplicate by source ref
- write/update at most one Honcho message per source ref

## Storage

Store entity-linking state in PostgreSQL for the experiment.

Minimum tables or equivalent models:

- `canonical_entities`
- `source_identities`
- `entity_aliases`
- `entity_candidates`
- `link_decisions`
- `routing_decisions`
- `source_import_state`
- `honcho_write_receipts`

Every routing decision must keep:

- source ref
- selected peer
- selected Honcho peer id
- employee fallback peer
- aggregate fallback peer
- candidate list
- confidence
- rule version
- timestamp

Every source import state must keep:

- source name
- last successful sync timestamp
- checkpoint/cursor payload when available
- overlap window used
- latest imported source timestamp

Every Honcho write receipt must keep:

- source ref
- selected peer
- session id
- Honcho message id or deterministic client message id
- write timestamp

## Evaluation

Start with a small hand-labeled set:

- Linear issues mentioning employees
- Linear issues with assignees
- Linear issues with creators and no assignee
- Linear issues with unmatched users and team fallback
- repeated imports of changed and unchanged Linear issues
- Iteration 2: Linear issues mentioning CRM people/companies that produce
  candidate metadata without default company peer writes

Metrics:

- correct high-confidence links
- false positive specific links
- missed specific links
- fallback rate
- ambiguous candidate rate
- provisional/no-write rate

Primary quality rule:

```text
False positive CRM/company links are worse than unresolved or provisional links,
because wrong Honcho peer writes contaminate durable memory. Employee fallback is
only an attribution fallback, not a guessed subject link.
```

## Out Of Scope

- full production entity resolution
- automatic fuzzy employee merges
- graph database
- LLM-only entity creation
- human review UI
- governance/PII policy enforcement for Honcho writes
- automatic merges for CRM people/companies
- Slack and GOG ingestion in the first implementation slice
- CRM/company candidate linking in Iteration 1

## Open Questions

- Should unresolved candidates create provisional entities, or wait for a human
  review workflow?
- Should Honcho receive mirrored messages for high-signal actor/assignee events,
  or should employees stay metadata-only for the experiment?
- What evidence threshold makes a CRM/company link salient enough for a derived
  Honcho peer write?
