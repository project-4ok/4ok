import pytest

from gcb.governance.identity import principal_from_trusted_claims


def test_principal_from_trusted_claims_maps_subject_agent_and_groups() -> None:
    principal = principal_from_trusted_claims(
        {
            "sub": "user-123",
            "email": "finance@example.com",
            "groups": ["finance", "group:ops", 42],
        },
        agent_id="agent:context-helper",
    )

    assert principal.human_id == "human:user-123"
    assert principal.agent_id == "agent:context-helper"
    assert principal.roles == ("finance", "group:ops")


def test_principal_from_trusted_claims_falls_back_to_email_identifier() -> None:
    principal = principal_from_trusted_claims(
        {
            "email": "Finance.User@Example.com",
            "roles": ["operator"],
        },
        agent_id="agent:context-helper",
    )

    assert principal.human_id == "human:email:finance.user@example.com"
    assert principal.roles == ("operator",)


def test_principal_from_trusted_claims_supports_realm_access_roles() -> None:
    principal = principal_from_trusted_claims(
        {
            "sub": "user-123",
            "realm_access": {"roles": ["finance", "offline_access"]},
        },
        agent_id="agent:context-helper",
    )

    assert principal.roles == ("finance", "offline_access")


def test_principal_from_trusted_claims_requires_human_identifier() -> None:
    with pytest.raises(ValueError, match="trusted identity claims require sub or email"):
        principal_from_trusted_claims({"groups": ["finance"]}, agent_id="agent:context-helper")


def test_principal_from_trusted_claims_requires_agent_identifier() -> None:
    with pytest.raises(ValueError, match="agent_id is required"):
        principal_from_trusted_claims({"sub": "user-123"}, agent_id="")
