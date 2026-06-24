import json

from gcb.governance.deferred_reveal_policy import CerbosRevealPolicy, StaticRevealPolicy
from gcb.governance.policy import PrincipalContext

PRINCIPAL = PrincipalContext(human_id="human:finance-1", agent_id="agent:context-helper")


def test_static_reveal_policy_allows_only_payment_iban_reveal() -> None:
    policy = StaticRevealPolicy()

    allowed = policy.check_reveal(
        token_type="iban", purpose="payment_processing", principal=PRINCIPAL
    )
    missing_purpose = policy.check_reveal(token_type="iban", purpose="", principal=PRINCIPAL)
    wrong_purpose = policy.check_reveal(
        token_type="iban", purpose="customer_support", principal=PRINCIPAL
    )
    wrong_field = policy.check_reveal(
        token_type="email", purpose="payment_processing", principal=PRINCIPAL
    )

    assert allowed.allowed is True
    assert allowed.policy_id == "static-reveal-policy"
    assert missing_purpose.allowed is False
    assert missing_purpose.reason == "purpose_required"
    assert wrong_purpose.allowed is False
    assert wrong_purpose.reason == "purpose_not_allowed"
    assert wrong_field.allowed is False
    assert wrong_field.reason == "purpose_not_allowed"


def test_cerbos_reveal_policy_maps_resource_check_response(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def read(self):
            return json.dumps(
                {
                    "results": [
                        {
                            "resource": {"policyVersion": "v1"},
                            "actions": {"reveal": "EFFECT_ALLOW"},
                            "meta": {
                                "actions": {"reveal": {"matchedPolicy": "resource.token_field.vv1"}}
                            },
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("gcb.governance.deferred_reveal_policy.request.urlopen", fake_urlopen)

    decision = CerbosRevealPolicy(endpoint="http://cerbos:3592").check_reveal(
        token_type="iban", purpose="payment_processing", principal=PRINCIPAL
    )

    assert captured["url"] == "http://cerbos:3592/api/check/resources"
    assert captured["body"]["includeMeta"] is True
    assert captured["body"]["principal"]["id"] == "human:finance-1"
    assert captured["body"]["principal"]["attr"]["agent_id"] == "agent:context-helper"
    assert captured["body"]["resources"][0]["resource"]["kind"] == "token_field"
    assert captured["body"]["resources"][0]["resource"]["policyVersion"] == "v1"
    assert captured["body"]["resources"][0]["actions"] == ["reveal"]
    assert captured["timeout"] == 5
    assert decision.allowed is True
    assert decision.policy_id == "resource.token_field.vv1"
    assert decision.policy_version == "v1"


def test_cerbos_reveal_policy_maps_denied_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def read(self):
            return json.dumps(
                {
                    "results": [
                        {
                            "resource": {"policyVersion": "v1"},
                            "actions": {"reveal": "EFFECT_DENY"},
                            "meta": {
                                "actions": {"reveal": {"matchedPolicy": "resource.token_field.vv1"}}
                            },
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr(
        "gcb.governance.deferred_reveal_policy.request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    decision = CerbosRevealPolicy(endpoint="http://cerbos:3592").check_reveal(
        token_type="iban", purpose="customer_support", principal=PRINCIPAL
    )

    assert decision.allowed is False
    assert decision.reason == "purpose_not_allowed"
    assert decision.policy_id == "resource.token_field.vv1"
    assert decision.policy_version == "v1"
