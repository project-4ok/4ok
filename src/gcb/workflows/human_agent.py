from __future__ import annotations

from dataclasses import dataclass

from gcb.governance import GovernedContext
from gcb.governance.policy import PrincipalContext


@dataclass(frozen=True)
class EvidenceItem:
    source_ref: str
    subject: str
    timestamp: str
    text: str


@dataclass(frozen=True)
class WorkflowSearchResponse:
    summary: str
    evidence: list[EvidenceItem]


class AgentToolFacade:
    def __init__(self, context: GovernedContext, principal: PrincipalContext) -> None:
        self._context = context
        self._principal = principal

    def search_context(self, query: str, *, limit: int = 5) -> WorkflowSearchResponse:
        response = self._context.search_context(
            query,
            limit=limit,
            principal=self._principal,
        )
        evidence = [
            EvidenceItem(
                source_ref=result.source_ref,
                subject=result.subject,
                timestamp=result.date,
                text=result.snippet,
            )
            for result in response.results
        ]
        return WorkflowSearchResponse(
            summary=_summary_for(evidence),
            evidence=evidence,
        )


class HumanAgentWorkflow:
    def __init__(self, context: GovernedContext, principal: PrincipalContext) -> None:
        self._context = context
        self._tools = AgentToolFacade(context, principal)

    def ask(self, query: str, *, limit: int = 5) -> WorkflowSearchResponse:
        return self._tools.search_context(query, limit=limit)

    def audit_trail(self) -> list[dict[str, object]]:
        return self._context.audit_events()


def _summary_for(evidence: list[EvidenceItem]) -> str:
    if not evidence:
        return "No matching governed evidence was found."
    if len(evidence) == 1:
        return "Found 1 governed evidence item for human review."
    return f"Found {len(evidence)} governed evidence items for human review."
