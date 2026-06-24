from pathlib import Path

from gcb.etl.extract.email_parser import load_email_dir
from gcb.governance import GovernedContext
from gcb.governance.policy import PrincipalContext
from gcb.workflows import AgentToolFacade, HumanAgentWorkflow

FIXTURES = Path(__file__).parents[2] / "fixtures" / "emails"
RAW_IBAN = "DE89370400440532013000"


def build_workflow() -> HumanAgentWorkflow:
    context = GovernedContext()
    context.ingest(load_email_dir(FIXTURES))
    return HumanAgentWorkflow(
        context,
        PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
    )


def build_tools() -> AgentToolFacade:
    context = GovernedContext()
    context.ingest(load_email_dir(FIXTURES))
    return AgentToolFacade(
        context,
        PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
    )


def build_context_and_tools() -> tuple[GovernedContext, AgentToolFacade]:
    context = GovernedContext()
    context.ingest(load_email_dir(FIXTURES))
    tools = AgentToolFacade(
        context,
        PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
    )
    return context, tools


def test_agent_tool_facade_exposes_only_search_tool() -> None:
    tools = build_tools()

    public_methods = {
        name for name in dir(tools) if not name.startswith("_") and callable(getattr(tools, name))
    }

    assert public_methods == {"search_context"}


def test_agent_tool_facade_search_returns_raw_internal_evidence_without_reveal_tokens() -> None:
    tools = build_tools()

    response = tools.search_context("refund iban canceled account", limit=3)

    assert response.summary == "Found 3 governed evidence items for human review."
    assert any(item.source_ref == "local_email:0013-refund-iban" for item in response.evidence)
    assert "BANK_ACCOUNT_" not in str(response)


def test_workflow_returns_human_visible_raw_internal_evidence() -> None:
    workflow = build_workflow()

    response = workflow.ask("refund iban canceled account", limit=3)

    assert response.summary == "Found 3 governed evidence items for human review."
    assert any(item.source_ref == "local_email:0013-refund-iban" for item in response.evidence)
    assert response.evidence[0].text
    assert "BANK_ACCOUNT_" not in str(response)


def test_workflow_reports_empty_evidence() -> None:
    workflow = build_workflow()

    response = workflow.ask("zzzzzz-not-found")

    assert response.summary == "No matching governed evidence was found."
    assert response.evidence == []
