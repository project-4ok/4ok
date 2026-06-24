from gcb.governance.permissions import (
    decode_json_string_list,
    decode_permission_refs,
    principal_permission_refs,
    transitive_group_refs,
)
from gcb.governance.policy import PrincipalContext


def test_decode_permission_refs_accepts_only_json_string_lists() -> None:
    assert decode_permission_refs('["finance", "group:ops", 12]') == {
        "finance",
        "group:ops",
    }
    assert decode_permission_refs("{}") == set()
    assert decode_permission_refs("not-json") == set()


def test_decode_json_string_list_preserves_ordered_string_values() -> None:
    assert decode_json_string_list('["a", 1, "b"]') == ["a", "b"]


def test_principal_permission_refs_include_roles_groups_human_and_inherited_groups() -> None:
    refs = principal_permission_refs(
        PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
        {"group:finance": ("group:company",), "group:company": ("group:all",)},
    )

    assert refs == {
        "finance",
        "group:finance",
        "group:company",
        "group:all",
        "human:finance-1",
    }


def test_transitive_group_refs_ignores_cycles() -> None:
    assert transitive_group_refs(
        {"group:a"},
        {"group:a": ("group:b",), "group:b": ("group:a",)},
    ) == {"group:a", "group:b"}
