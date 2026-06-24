from __future__ import annotations

import json

from fourok.governance.policy import PrincipalContext


def decode_permission_refs(raw_value: str) -> set[str]:
    return set(decode_json_string_list(raw_value))


def decode_json_string_list(raw_value: str) -> list[str]:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def principal_permission_refs(
    principal: PrincipalContext, group_inheritance: dict[str, tuple[str, ...]]
) -> set[str]:
    refs = set(principal.roles)
    refs.update(f"group:{role}" for role in principal.roles)
    refs.add(principal.human_id)
    refs.update(transitive_group_refs(refs, group_inheritance))
    return refs


def transitive_group_refs(
    permission_refs: set[str], group_inheritance: dict[str, tuple[str, ...]]
) -> set[str]:
    expanded = set()
    pending = [ref for ref in permission_refs if ref.startswith("group:")]
    while pending:
        child = pending.pop()
        for parent in group_inheritance.get(child, ()):
            if parent in expanded:
                continue
            expanded.add(parent)
            if parent.startswith("group:"):
                pending.append(parent)
    return expanded
