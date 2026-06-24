# Plan

Active roadmap only. Source code and executable tests are truth for implemented
behavior. Completed history belongs in `CHANGELOG.md` or `reports/`.

## Docs Policy

Keep docs only for unimplemented plans, operator commands, architectural
decisions, risks, and research. Do not duplicate implemented behavior across
multiple docs.

Owning docs:

- `docs/goal.md`: current gates only.
- `docs/operations.md`: run/check/debug commands.
- `docs/contracts.md`: unimplemented or external-facing contracts.
- `docs/review.md`: risks, deferrals, human-review items.
- Research docs: keep experiments out of active plans.
- `reports/`: evidence history.

## Active Work Queue

1. Stage 1: close cleanup gates and leave local proof trustworthy.
   Finish only the gates in `docs/goal.md`: live case refresh,
   `stage1-acceptance`, Grafana/Dagster freshness, semantic tracing for Dagster
   runs/assets, DX/AX resume state, useful refactors, and final restart proof.
2. Stage 2: ship local OpenClaw product value.
   Build the OpenClaw plugin RAG hook. Before each prompt, inject a short,
   permission-aware 4OK source summary with refs, timestamps, and limitations.
   The agent should not call the 4OK CLI as the product path.
3. Stage 3: improve retrieval usefulness for real questions.
   Use 5-10 approved live questions to improve query generation, snippets,
   ranking, limitations, and provenance. Investigate whether query expansion
   should be implemented, including whether `https://github.com/tobi/qmd` is a
   useful reference or dependency. Add graph/semantic machinery only when these
   questions prove it is needed.
4. Stage 4: deploy internal production off the local workstation.
   Move the proven local runtime to server-backed Compose, preferably the fourok
   gateway. Prove secrets, volumes, backups, image tags, rollback, health, and
   monitored access.
5. Stage 5: add source-backed relationships that improve answers.
   Add Drive folder/owner, Slack channel/thread/user, Linear issue/team/state,
   Twenty person/company/deal, and strong cross-source matches only after the
   OpenClaw loop is useful.

## Slice Constraints

- DX, AX, tests, and refactoring are constraints inside product slices, not a
  separate endless cleanup track.
- If cleanup does not unlock a product proof or reduce repeated verification
  cost, defer it.
- Use Codex only for large or parallel independent implementation slices.

## Near-Term Non-Goals

- final GDPR-compliant PII architecture
- universal masking/tokenization
- reveal workflow or field-level reveal authorization
- production broker choice
- Kubernetes or multi-host deployment
- OCR/image PDF/layout/table extraction
- Honcho or Graphiti as the primary company context substrate

## Deferred Backlog

- Source-backed consolidation/object cards.
- Full governance: PII/tokenization, reveal policy, retention/deletion drills.
- Notion and Jira connectors.
- GitHub knowledge import: repos, issues, PRs, reviews, discussions, and commit
  metadata as permission-aware source records with provenance.
- Real SaaS webhooks after batch/backfill and OpenClaw value are usable.
- Probabilistic entity linking and human review workflow.
- Advanced retrieval: `read_source`, `record_decision`, semantic/vector main path,
  query planning over related objects.
- Production infrastructure beyond server-backed Compose.

## Open Questions

- Which permission model is good enough before broader Workspace/Gmail data is
  trusted by users?
- Should deferred PII/reveal and memory experiments move behind a clearer
  experimental package boundary?
- What minimum restore-drill evidence is needed before calling internal v0
  deployable?
- When does webhook volume justify a real broker?
