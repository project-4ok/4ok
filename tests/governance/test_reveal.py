from sqlalchemy import MetaData, select

from fourok.governance.deferred_reveal_policy import (
    RevealPolicy,
    RevealPolicyDecision,
    StaticRevealPolicy,
)
from fourok.governance.policy import PrincipalContext
from fourok.governance.reveal import request_reveal
from fourok.governance.state import create_governed_context_state
from fourok.governance.token_store import token_for, token_store_table

PRINCIPAL = PrincipalContext(human_id="human:finance", agent_id="agent:context")


def deferred_token_store(state):
    metadata = MetaData()
    token_store = token_store_table(metadata)
    token_store.create(state.engine)
    return token_store


class DenyFinanceRevealPolicy(RevealPolicy):
    def check_reveal(
        self,
        *,
        token_type: str,
        purpose: str,
        principal: PrincipalContext,
    ) -> RevealPolicyDecision:
        return RevealPolicyDecision(
            allowed=False,
            reason="principal_not_allowed",
            policy_id="test-deny-finance-reveal-policy",
            policy_version="v1",
        )


class AllowFinanceRevealPolicy(RevealPolicy):
    def check_reveal(
        self,
        *,
        token_type: str,
        purpose: str,
        principal: PrincipalContext,
    ) -> RevealPolicyDecision:
        if principal.human_id != "human:finance":
            return RevealPolicyDecision(
                allowed=False,
                reason="principal_not_allowed",
                policy_id="test-allow-finance-reveal-policy",
                policy_version="v1",
            )
        if purpose != "pilot_review":
            return RevealPolicyDecision(
                allowed=False,
                reason="purpose_not_allowed",
                policy_id="test-allow-finance-reveal-policy",
                policy_version="v1",
            )
        return RevealPolicyDecision(
            allowed=True,
            reason="allowed",
            policy_id="test-allow-finance-reveal-policy",
            policy_version="v1",
        )


def test_request_reveal_allows_policy_checked_token_and_records_audit() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    token_store = deferred_token_store(state)
    token = token_for(
        state.engine,
        token_store,
        token_type="iban",
        raw_value="DE89370400440532013000",
    )

    decision = request_reveal(
        state.engine,
        token_store=token_store,
        audit_events=state.audit_events,
        reveal_policy=StaticRevealPolicy(),
        token=token,
        purpose="payment_processing",
        principal=PRINCIPAL,
    )

    assert decision == {
        "status": "allowed",
        "token": token,
        "type": "iban",
        "value": "DE89370400440532013000",
        "policy_id": "static-reveal-policy",
        "policy_version": "v0",
    }
    with state.engine.connect() as connection:
        audit_event = connection.execute(select(state.audit_events)).mappings().one()
    assert audit_event["event_type"] == "reveal"
    assert audit_event["token"] == token
    assert audit_event["purpose"] == "payment_processing"
    assert audit_event["decision"] == "allowed"
    assert audit_event["policy_id"] == "static-reveal-policy"
    assert audit_event["policy_version"] == "v0"
    assert audit_event["human_id"] == "human:finance"


def test_request_reveal_denies_missing_token_without_policy_metadata() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    token_store = deferred_token_store(state)

    decision = request_reveal(
        state.engine,
        token_store=token_store,
        audit_events=state.audit_events,
        reveal_policy=StaticRevealPolicy(),
        token="BANK_ACCOUNT_UNKNOWN",
        purpose="payment_processing",
        principal=PRINCIPAL,
    )

    assert decision == {
        "status": "denied",
        "token": "BANK_ACCOUNT_UNKNOWN",
        "reason": "token_not_found",
    }
    with state.engine.connect() as connection:
        audit_event = connection.execute(select(state.audit_events)).mappings().one()
    assert audit_event["event_type"] == "reveal"
    assert audit_event["decision"] == "denied"
    assert audit_event["reason"] == "token_not_found"
    assert audit_event["policy_id"] == ""
    assert audit_event["policy_version"] == ""


def test_request_reveal_denies_when_policy_rejects_principal_and_audits_decision() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    token_store = deferred_token_store(state)
    token = token_for(
        state.engine,
        token_store,
        token_type="iban",
        raw_value="DE44500105175407324931",
    )

    decision = request_reveal(
        state.engine,
        token_store=token_store,
        audit_events=state.audit_events,
        reveal_policy=DenyFinanceRevealPolicy(),
        token=token,
        purpose="pilot_review",
        principal=PRINCIPAL,
    )

    assert decision == {
        "status": "denied",
        "token": token,
        "type": "iban",
        "reason": "principal_not_allowed",
        "policy_id": "test-deny-finance-reveal-policy",
        "policy_version": "v1",
    }
    with state.engine.connect() as connection:
        audit_event = connection.execute(select(state.audit_events)).mappings().one()
    assert audit_event["decision"] == "denied"
    assert audit_event["reason"] == "principal_not_allowed"
    assert audit_event["policy_id"] == "test-deny-finance-reveal-policy"
    assert audit_event["policy_version"] == "v1"


def test_request_reveal_allows_when_policy_and_principal_match_and_audits_decision() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    token_store = deferred_token_store(state)
    token = token_for(
        state.engine,
        token_store,
        token_type="iban",
        raw_value="DE44500105175407324931",
    )

    decision = request_reveal(
        state.engine,
        token_store=token_store,
        audit_events=state.audit_events,
        reveal_policy=AllowFinanceRevealPolicy(),
        token=token,
        purpose="pilot_review",
        principal=PRINCIPAL,
    )

    assert decision == {
        "status": "allowed",
        "token": token,
        "type": "iban",
        "value": "DE44500105175407324931",
        "policy_id": "test-allow-finance-reveal-policy",
        "policy_version": "v1",
    }
    with state.engine.connect() as connection:
        audit_event = connection.execute(select(state.audit_events)).mappings().one()
    assert audit_event["decision"] == "allowed"
    assert audit_event["reason"] == ""
    assert audit_event["policy_id"] == "test-allow-finance-reveal-policy"
    assert audit_event["policy_version"] == "v1"
