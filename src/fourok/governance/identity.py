from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fourok.governance.policy import PrincipalContext


def principal_from_trusted_claims(
    claims: Mapping[str, Any],
    *,
    agent_id: str,
) -> PrincipalContext:
    if not agent_id:
        raise ValueError("agent_id is required")

    human_id = _human_id(claims)
    roles = tuple(_unique_strings([*_claim_strings(claims, "groups"), *_role_claims(claims)]))
    return PrincipalContext(
        human_id=human_id,
        agent_id=agent_id,
        roles=roles or ("operator",),
    )


def _human_id(claims: Mapping[str, Any]) -> str:
    subject = claims.get("sub")
    if isinstance(subject, str) and subject:
        return f"human:{subject}"

    email = claims.get("email")
    if isinstance(email, str) and email:
        return f"human:email:{email.strip().casefold()}"

    raise ValueError("trusted identity claims require sub or email")


def _role_claims(claims: Mapping[str, Any]) -> list[str]:
    roles = _claim_strings(claims, "roles")
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, Mapping):
        roles.extend(_strings(realm_access.get("roles")))
    return roles


def _claim_strings(claims: Mapping[str, Any], name: str) -> list[str]:
    return _strings(claims.get(name))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _unique_strings(values: list[str]) -> list[str]:
    unique = []
    seen = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        unique.append(normalized)
        seen.add(normalized)
    return unique
