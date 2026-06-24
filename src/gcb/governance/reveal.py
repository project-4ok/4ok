"""Deferred reveal experiment.

This module is intentionally not exported from ``gcb.governance`` and is not
part of the active internal runtime surface.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from gcb.governance.audit import record_audit_event
from gcb.governance.deferred_reveal_policy import RevealPolicy
from gcb.governance.policy import PrincipalContext
from gcb.governance.token_store import find_token_row


def request_reveal(
    engine: Engine,
    *,
    token_store: Table,
    audit_events: Table,
    reveal_policy: RevealPolicy,
    token: str,
    purpose: str,
    principal: PrincipalContext,
) -> dict[str, str]:
    token_record = find_token_row(engine, token_store, token)
    if token_record is None:
        decision = {"status": "denied", "token": token, "reason": "token_not_found"}
        policy_id = ""
        policy_version = ""
    else:
        policy_decision = reveal_policy.check_reveal(
            token_type=token_record["token_type"],
            purpose=purpose,
            principal=principal,
        )
        if policy_decision.allowed:
            decision = {
                "status": "allowed",
                "token": token_record["token"],
                "type": token_record["token_type"],
                "value": token_record["raw_value"],
                "policy_id": policy_decision.policy_id,
                "policy_version": policy_decision.policy_version,
            }
        else:
            decision = {
                "status": "denied",
                "token": token,
                "type": token_record["token_type"],
                "reason": policy_decision.reason,
                "policy_id": policy_decision.policy_id,
                "policy_version": policy_decision.policy_version,
            }
        policy_id = policy_decision.policy_id
        policy_version = policy_decision.policy_version

    record_audit_event(
        engine,
        audit_events,
        "reveal",
        {
            "token": token,
            "purpose": purpose,
            "principal": principal,
            "decision": decision["status"],
            "reason": decision.get("reason", ""),
            "policy_id": policy_id,
            "policy_version": policy_version,
        },
    )
    return decision
