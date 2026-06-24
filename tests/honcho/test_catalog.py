import json
from pathlib import Path

from gcb.honcho.catalog import CatalogEmployee, import_source_catalogs

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures" / "honcho" / "linear_twenty_slack_sample.json"
)


def test_import_source_catalogs_builds_employees_from_twenty_workspace_members() -> None:
    catalog = import_source_catalogs(json.loads(FIXTURE.read_text(encoding="utf-8")))

    assert catalog.summary == {
        "twenty_workspace_members": 1,
        "slack_users": 1,
        "linear_users": 1,
        "linear_teams": 1,
        "linear_projects": 1,
        "employees": 1,
        "source_identities": 3,
        "unresolved_linear_users": 0,
        "unresolved_slack_users": 0,
    }
    assert catalog.employees["employee:email:olivia@example.com"].to_dict() == {
        "entity_ref": "employee:email:olivia@example.com",
        "display_name": "Olivia Smith",
        "primary_email": "olivia@example.com",
        "honcho_peer_id": "slack_U123456",
        "source_identities": [
            "twenty:workspaceMember:twenty-member-olivia",
            "slack:user:U123456",
            "linear:user:linear-user-olivia",
        ],
    }


def test_import_source_catalogs_does_not_create_employees_from_linear_only_users() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_users"].append(
        {
            "id": "linear-user-external",
            "display_name": "External User",
            "email": "external@example.com",
        }
    )

    catalog = import_source_catalogs(data)

    assert "employee:email:external@example.com" not in catalog.employees
    assert catalog.summary["unresolved_linear_users"] == 1


def test_import_source_catalogs_keeps_linear_teams_and_projects() -> None:
    catalog = import_source_catalogs(json.loads(FIXTURE.read_text(encoding="utf-8")))

    assert catalog.linear_teams == {
        "linear:team:ops": {
            "source_ref": "linear:team:ops",
            "source_id": "ops",
            "key": "OPS",
            "name": "Operations",
        }
    }
    assert catalog.linear_projects == {
        "linear:project:project-meetings": {
            "source_ref": "linear:project:project-meetings",
            "source_id": "project-meetings",
            "name": "Meeting Operations",
        }
    }


def test_import_source_catalogs_reuses_existing_employee_catalog_when_twenty_is_absent() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["twenty_workspace_members"] = []

    catalog = import_source_catalogs(
        data,
        existing_employees={
            "employee:email:olivia@example.com": CatalogEmployee(
                entity_ref="employee:email:olivia@example.com",
                display_name="Olivia Smith",
                primary_email="olivia@example.com",
                source_identities=["twenty:workspaceMember:twenty-member-olivia"],
            )
        },
    )

    employee = catalog.employees["employee:email:olivia@example.com"]
    assert employee.honcho_peer_id == "slack_U123456"
    assert catalog.linear_user_employee_refs == {
        "linear-user-olivia": "employee:email:olivia@example.com"
    }
    assert employee.source_identities == [
        "twenty:workspaceMember:twenty-member-olivia",
        "slack:user:U123456",
        "linear:user:linear-user-olivia",
    ]


def test_import_source_catalogs_clears_deleted_slack_peer_mapping() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["twenty_workspace_members"] = []
    data["linear_users"] = []
    data["slack_users"][0]["deleted"] = True

    catalog = import_source_catalogs(
        data,
        existing_employees={
            "employee:email:olivia@example.com": CatalogEmployee(
                entity_ref="employee:email:olivia@example.com",
                display_name="Olivia Smith",
                primary_email="olivia@example.com",
                honcho_peer_id="slack_U123456",
                source_identities=[
                    "twenty:workspaceMember:twenty-member-olivia",
                    "slack:user:U123456",
                ],
            )
        },
    )

    employee = catalog.employees["employee:email:olivia@example.com"]
    assert employee.honcho_peer_id is None
    assert employee.source_identities == [
        "twenty:workspaceMember:twenty-member-olivia",
        "slack:user:U123456",
    ]


def test_import_source_catalogs_moves_slack_peer_when_user_email_changes() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["twenty_workspace_members"][0]["email"] = "olivia.new@example.com"
    data["slack_users"][0]["email"] = "olivia.new@example.com"
    data["linear_users"] = []

    catalog = import_source_catalogs(
        data,
        existing_employees={
            "employee:email:olivia@example.com": CatalogEmployee(
                entity_ref="employee:email:olivia@example.com",
                display_name="Olivia Smith",
                primary_email="olivia@example.com",
                honcho_peer_id="slack_U123456",
                source_identities=[
                    "twenty:workspaceMember:twenty-member-olivia",
                    "slack:user:U123456",
                ],
            )
        },
    )

    old_employee = catalog.employees["employee:email:olivia@example.com"]
    new_employee = catalog.employees["employee:email:olivia.new@example.com"]
    assert old_employee.honcho_peer_id is None
    assert new_employee.honcho_peer_id == "slack_U123456"
    assert new_employee.source_identities == [
        "twenty:workspaceMember:twenty-member-olivia",
        "slack:user:U123456",
    ]
