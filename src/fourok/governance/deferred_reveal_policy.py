"""Deferred reveal-policy experiment.

This module is intentionally outside the active governance policy module. The
current internal runtime does not expose a reveal tool or field reveal policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from fourok.governance.policy import PrincipalContext


@dataclass(frozen=True)
class RevealPolicyDecision:
    allowed: bool
    reason: str
    policy_id: str
    policy_version: str


class RevealPolicy:
    def check_reveal(
        self,
        *,
        token_type: str,
        purpose: str,
        principal: PrincipalContext,
    ) -> RevealPolicyDecision:
        raise NotImplementedError


class StaticRevealPolicy(RevealPolicy):
    def check_reveal(
        self,
        *,
        token_type: str,
        purpose: str,
        principal: PrincipalContext,
    ) -> RevealPolicyDecision:
        if not purpose:
            return RevealPolicyDecision(
                allowed=False,
                reason="purpose_required",
                policy_id="static-reveal-policy",
                policy_version="v0",
            )
        if token_type == "iban" and purpose == "payment_processing":
            return RevealPolicyDecision(
                allowed=True,
                reason="allowed",
                policy_id="static-reveal-policy",
                policy_version="v0",
            )
        return RevealPolicyDecision(
            allowed=False,
            reason="purpose_not_allowed",
            policy_id="static-reveal-policy",
            policy_version="v0",
        )
