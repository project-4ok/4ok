from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CatalogEmployee:
    entity_ref: str
    display_name: str
    primary_email: str
    honcho_peer_id: str | None = None
    source_identities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_ref": self.entity_ref,
            "display_name": self.display_name,
            "primary_email": self.primary_email,
            "honcho_peer_id": self.honcho_peer_id,
            "source_identities": self.source_identities,
        }


@dataclass(frozen=True)
class SourceCatalog:
    employees: dict[str, CatalogEmployee]
    employee_by_email: dict[str, CatalogEmployee]
    linear_user_employee_refs: dict[str, str]
    linear_teams: dict[str, dict[str, object]]
    linear_projects: dict[str, dict[str, object]]
    summary: dict[str, int]

    def employee_for_linear_user(self, user_id: object) -> CatalogEmployee | None:
        if not isinstance(user_id, str):
            return None
        employee_ref = self.linear_user_employee_refs.get(user_id)
        if employee_ref is None:
            return None
        return self.employees.get(employee_ref)


def import_source_catalogs(
    data: dict[str, object],
    *,
    existing_employees: dict[str, CatalogEmployee] | None = None,
) -> SourceCatalog:
    employees = _copy_employees(existing_employees or {})
    employee_by_email: dict[str, CatalogEmployee] = {}
    for employee in employees.values():
        employee_by_email[employee.primary_email] = employee

    for member in _records(data, "twenty_workspace_members"):
        email = normalize_email(member.get("email"))
        if email is None:
            continue
        entity_ref = f"employee:email:{email}"
        employee = employees.get(entity_ref) or CatalogEmployee(
            entity_ref=entity_ref,
            display_name="",
            primary_email=email,
        )
        employee.display_name = str(member.get("display_name") or email)
        employee.primary_email = email
        _append_unique(employee.source_identities, f"twenty:workspaceMember:{member.get('id')}")
        employees[entity_ref] = employee
        employee_by_email[email] = employee

    unresolved_slack_users = _apply_slack_identities(data, employee_by_email)
    linear_user_employee_refs, unresolved_linear_users = _apply_linear_user_identities(
        data, employee_by_email
    )
    linear_teams = _linear_teams(data)
    linear_projects = _linear_projects(data)

    return SourceCatalog(
        employees=employees,
        employee_by_email=employee_by_email,
        linear_user_employee_refs=linear_user_employee_refs,
        linear_teams=linear_teams,
        linear_projects=linear_projects,
        summary={
            "twenty_workspace_members": len(_records(data, "twenty_workspace_members")),
            "slack_users": len(_records(data, "slack_users")),
            "linear_users": len(_records(data, "linear_users")),
            "linear_teams": len(_records(data, "linear_teams")),
            "linear_projects": len(_records(data, "linear_projects")),
            "employees": len(employees),
            "source_identities": sum(
                len(employee.source_identities) for employee in employees.values()
            ),
            "unresolved_linear_users": unresolved_linear_users,
            "unresolved_slack_users": unresolved_slack_users,
        },
    )


def normalize_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip().lower()
    return stripped or None


def records(data: dict[str, object], key: str) -> list[dict[str, object]]:
    return _records(data, key)


def _apply_slack_identities(
    data: dict[str, object], employee_by_email: dict[str, CatalogEmployee]
) -> int:
    unresolved = 0
    for user in _records(data, "slack_users"):
        user_id = user.get("id")
        if not isinstance(user_id, str):
            continue
        if user.get("deleted"):
            _clear_slack_peer(employee_by_email, user_id)
            continue
        if user.get("is_bot"):
            continue
        email = normalize_email(user.get("email"))
        if email is None:
            continue
        employee = employee_by_email.get(email)
        if employee is None:
            unresolved += 1
            continue
        _clear_slack_peer(employee_by_email, user_id)
        employee.honcho_peer_id = f"slack_{user_id}"
        _append_unique(employee.source_identities, f"slack:user:{user_id}")
    return unresolved


def _clear_slack_peer(employee_by_email: dict[str, CatalogEmployee], user_id: str) -> None:
    slack_peer_id = f"slack_{user_id}"
    for employee in employee_by_email.values():
        if employee.honcho_peer_id == slack_peer_id:
            employee.honcho_peer_id = None


def _apply_linear_user_identities(
    data: dict[str, object], employee_by_email: dict[str, CatalogEmployee]
) -> tuple[dict[str, str], int]:
    linear_user_employee_refs: dict[str, str] = {}
    unresolved = 0
    for user in _records(data, "linear_users"):
        email = normalize_email(user.get("email"))
        if email is None:
            continue
        employee = employee_by_email.get(email)
        if employee is None:
            unresolved += 1
            continue
        user_id = user.get("id")
        if not isinstance(user_id, str):
            continue
        linear_user_employee_refs[user_id] = employee.entity_ref
        _append_unique(employee.source_identities, f"linear:user:{user_id}")
    return linear_user_employee_refs, unresolved


def _linear_teams(data: dict[str, object]) -> dict[str, dict[str, object]]:
    teams: dict[str, dict[str, object]] = {}
    for team in _records(data, "linear_teams"):
        team_id = team.get("id")
        if not isinstance(team_id, str):
            continue
        source_ref = f"linear:team:{team_id}"
        teams[source_ref] = {
            "source_ref": source_ref,
            "source_id": team_id,
            "key": team.get("key"),
            "name": team.get("name"),
        }
    return teams


def _linear_projects(data: dict[str, object]) -> dict[str, dict[str, object]]:
    projects: dict[str, dict[str, object]] = {}
    for project in _records(data, "linear_projects"):
        project_id = project.get("id")
        if not isinstance(project_id, str):
            continue
        source_ref = f"linear:project:{project_id}"
        projects[source_ref] = {
            "source_ref": source_ref,
            "source_id": project_id,
            "name": project.get("name"),
        }
    return projects


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _copy_employees(employees: dict[str, CatalogEmployee]) -> dict[str, CatalogEmployee]:
    return {
        key: CatalogEmployee(
            entity_ref=employee.entity_ref,
            display_name=employee.display_name,
            primary_email=employee.primary_email,
            honcho_peer_id=employee.honcho_peer_id,
            source_identities=list(employee.source_identities),
        )
        for key, employee in employees.items()
    }


def _records(data: dict[str, object], key: str) -> list[dict[str, object]]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
