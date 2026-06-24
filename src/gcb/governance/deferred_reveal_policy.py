"""Deferred reveal-policy experiment.

This module is intentionally outside the active governance policy module. The
current internal runtime does not expose a reveal tool or field reveal policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request

from gcb.governance.policy import PrincipalContext


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


class CerbosRevealPolicy(RevealPolicy):
    def __init__(self, *, endpoint: str) -> None:
        self._endpoint = endpoint.rstrip("/")

    def check_reveal(
        self,
        *,
        token_type: str,
        purpose: str,
        principal: PrincipalContext,
    ) -> RevealPolicyDecision:
        payload = {
            "requestId": "gcb-reveal-check",
            "includeMeta": True,
            "principal": {
                "id": principal.human_id,
                "roles": list(principal.roles),
                "attr": {"purpose": purpose, "agent_id": principal.agent_id},
            },
            "resources": [
                {
                    "resource": {
                        "id": f"token-field:{token_type}",
                        "kind": "token_field",
                        "policyVersion": "v1",
                        "attr": {"token_type": token_type, "purpose": purpose},
                    },
                    "actions": ["reveal"],
                }
            ],
        }
        http_request = request.Request(
            f"{self._endpoint}/api/check/resources",
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=5) as response:
            response_body = json.loads(response.read())

        resource = response_body["results"][0]
        action_result = resource["actions"]["reveal"]
        action_meta = resource.get("meta", {}).get("actions", {}).get("reveal", {})
        allowed = action_result == "EFFECT_ALLOW"
        return RevealPolicyDecision(
            allowed=allowed,
            reason="allowed" if allowed else "purpose_not_allowed",
            policy_id=action_meta.get("matchedPolicy", "cerbos-token-field"),
            policy_version=resource.get("resource", {}).get("policyVersion", "unknown"),
        )
