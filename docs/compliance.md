# Compliance

Engineering constraints for GDPR-shaped design. This is not legal advice.

## Core Position

Tokenized retrieval data is still personal data when re-identification is
possible. Treat the system as personal data processing.

Do not frame the product as generic agent long-term memory. The defensible
framing is controlled retrieval and controlled reveal for defined operational
purposes.

## Rules

- define a concrete purpose for stored facts and reveal workflows
- minimize raw PII copied into derived layers
- store direct identifiers in a protected token store
- embed/index sanitized text by default
- keep raw source data restricted
- propagate deletion and restriction to derived state
- require policy checks for reveal
- audit sensitive access and reveal decisions
- treat relationship graphs as sensitive, even when tokenized
- keep special-category/sensitive details out of embeddings by default

## Architecture Implications

Raw source layer:

- restricted storage
- retention/deletion controls
- not the default retrieval surface

Tokenization layer:

- detect direct identifiers early
- normalize and map them to stable tokens
- keep token mappings protected

Retrieval layer:

- metadata/policy filtering before semantic retrieval
- sanitized chunks and token placeholders by default
- evidence keeps source lineage

Reveal layer:

- authenticated requester
- explicit purpose
- field/workflow policy
- audit event for allow and deny

Audit layer:

- requester
- human and agent ids
- source/token/field
- purpose
- decision
- policy id/version
- timestamp

## Open Compliance Work

- lawful basis and privacy-notice review
- DPIA support material
- retention schedule by source and derived artifact
- data subject rights workflow
- production backup/encryption policy
- audit-log retention and review workflow
