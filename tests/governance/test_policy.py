from gcb.governance.deferred_reveal_policy import StaticRevealPolicy
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
