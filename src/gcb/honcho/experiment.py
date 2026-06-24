from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gcb.honcho.catalog import CatalogEmployee, SourceCatalog, import_source_catalogs, records


@dataclass(frozen=True)
class HonchoMessagePlan:
    peer: str
    session: str
    text: str
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "peer": self.peer,
            "session": self.session,
            "text": self.text,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class HonchoSyncPlan:
    summary: dict[str, int]
    messages: list[HonchoMessagePlan]
    employees: dict[str, CatalogEmployee]
    linear_teams: dict[str, dict[str, object]]
    linear_projects: dict[str, dict[str, object]]
    source_names: list[str]
    source_imports: dict[str, dict[str, str]]

    def to_dry_run_dict(self) -> dict[str, object]:
        return {
            "mode": "dry-run",
            "summary": self.summary,
            "messages": [message.to_dict() for message in self.messages],
        }


def load_honcho_fixture(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read Honcho sync fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Honcho sync fixture JSON: {path}") from exc


def build_honcho_sync_plan(
    data: dict[str, object],
    *,
    existing_employees: dict[str, CatalogEmployee] | None = None,
) -> HonchoSyncPlan:
    catalog = import_source_catalogs(data, existing_employees=existing_employees)
    messages: list[HonchoMessagePlan] = []
    unresolved_employee_refs: set[str] = set()

    for issue in records(data, "linear_issues"):
        creator = catalog.employee_for_linear_user(issue.get("creator_id"))
        assignee = catalog.employee_for_linear_user(issue.get("assignee_id"))
        selected = assignee or creator
        candidate_entities = _employee_refs([assignee, creator])
        aggregate_peer = f"linear:team:{issue.get('team_id') or 'unknown'}"
        peer, confidence = _selected_peer(
            selected,
            aggregate_peer=aggregate_peer,
            unresolved_employee_refs=unresolved_employee_refs,
        )

        messages.append(
            HonchoMessagePlan(
                peer=peer,
                session=f"{peer}:linear:{_event_month(issue)}",
                text=_issue_text(issue, creator=creator, assignee=assignee),
                metadata={
                    "source": "linear",
                    "source_ref": _issue_source_ref(issue),
                    "source_url": issue.get("url"),
                    "source_updated_at": issue.get("updated_at"),
                    "actors": _employee_refs([creator]),
                    "assignees": _employee_refs([assignee]),
                    "employee_peer": selected.entity_ref if selected else None,
                    "honcho_peer_id": selected.honcho_peer_id if selected else None,
                    "candidate_entities": candidate_entities,
                    **_permission_metadata(issue),
                    "aggregate_fallback_peer": aggregate_peer,
                    "routing_confidence": confidence,
                    "routing_rule": _routing_rule(assignee=assignee, creator=creator),
                },
            )
        )

    for comment in records(data, "linear_comments"):
        commenter = catalog.employee_for_linear_user(comment.get("user_id"))
        candidate_entities = _employee_refs([commenter])
        aggregate_peer = f"linear:team:{comment.get('team_id') or 'unknown'}"
        peer, confidence = _selected_peer(
            commenter,
            aggregate_peer=aggregate_peer,
            unresolved_employee_refs=unresolved_employee_refs,
        )

        messages.append(
            HonchoMessagePlan(
                peer=peer,
                session=f"{peer}:linear:{_event_month(comment)}",
                text=_comment_text(comment, commenter=commenter),
                metadata={
                    "source": "linear",
                    "source_ref": _comment_source_ref(comment),
                    "source_url": comment.get("url"),
                    "source_updated_at": comment.get("updated_at"),
                    "actors": _employee_refs([commenter]),
                    "assignees": [],
                    "employee_peer": commenter.entity_ref if commenter else None,
                    "honcho_peer_id": commenter.honcho_peer_id if commenter else None,
                    "candidate_entities": candidate_entities,
                    **_permission_metadata(comment),
                    "aggregate_fallback_peer": aggregate_peer,
                    "routing_confidence": confidence,
                    "routing_rule": _comment_routing_rule(commenter=commenter),
                    "related_issue_ref": _comment_related_issue_ref(comment),
                },
            )
        )

    return HonchoSyncPlan(
        summary={
            "twenty_workspace_members": catalog.summary["twenty_workspace_members"],
            "slack_users": catalog.summary["slack_users"],
            "linear_users": catalog.summary["linear_users"],
            "linear_issues": len(records(data, "linear_issues")),
            "linear_comments": len(records(data, "linear_comments")),
            "honcho_messages": len(messages),
            "unresolved_employee_mappings": len(unresolved_employee_refs),
            "unresolved_linear_users": catalog.summary["unresolved_linear_users"],
            "unresolved_slack_users": catalog.summary["unresolved_slack_users"],
        },
        messages=messages,
        employees=catalog.employees,
        linear_teams=catalog.linear_teams,
        linear_projects=catalog.linear_projects,
        source_names=_source_names(data),
        source_imports=_source_imports(data, catalog=catalog),
    )


def _issue_text(
    issue: dict[str, object],
    *,
    creator: CatalogEmployee | None,
    assignee: CatalogEmployee | None,
) -> str:
    creator_name = creator.display_name if creator else "Unknown user"
    assignee_name = assignee.display_name if assignee else "no assignee"
    text = (
        f"Linear issue {issue.get('identifier')}: {creator_name} created and assigned "
        f"{assignee_name} a task titled '{issue.get('title')}'."
    )
    description = _string_value(issue.get("description"))
    if description is not None:
        text = f"{text} Description: {description}"
    return text


def _comment_text(
    comment: dict[str, object],
    *,
    commenter: CatalogEmployee | None,
) -> str:
    commenter_name = commenter.display_name if commenter else "Unknown user"
    text = (
        f"Linear comment on {comment.get('issue_identifier')}: {commenter_name} "
        f"commented on '{comment.get('issue_title')}'."
    )
    body = _string_value(comment.get("body"))
    if body is not None:
        text = f"{text[:-1]}: {body}"
    return text


def _issue_source_ref(issue: dict[str, object]) -> str:
    return f"linear:issue:{issue.get('identifier')}"


def _comment_source_ref(comment: dict[str, object]) -> str:
    return f"linear:comment:{comment.get('id')}"


def _comment_related_issue_ref(comment: dict[str, object]) -> str:
    return f"linear:issue:{comment.get('issue_identifier')}"


def _event_month(issue: dict[str, object]) -> str:
    timestamp = str(issue.get("created_at") or issue.get("updated_at") or "")
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y-%m")
    except ValueError:
        return "unknown-month"


def _routing_rule(
    *,
    assignee: CatalogEmployee | None,
    creator: CatalogEmployee | None,
) -> str:
    if assignee is not None:
        return "linear_assignee_employee_match_v1"
    if creator is not None:
        return "linear_creator_employee_match_v1"
    return "linear_aggregate_fallback_v1"


def _comment_routing_rule(*, commenter: CatalogEmployee | None) -> str:
    if commenter is not None:
        return "linear_commenter_employee_match_v1"
    return "linear_aggregate_fallback_v1"


def _selected_peer(
    selected: CatalogEmployee | None,
    *,
    aggregate_peer: str,
    unresolved_employee_refs: set[str],
) -> tuple[str, str]:
    if selected is not None and selected.honcho_peer_id is not None:
        return selected.honcho_peer_id, "high"
    if selected is not None:
        unresolved_employee_refs.add(selected.entity_ref)
    return aggregate_peer, "fallback"


def _source_names(data: dict[str, object]) -> list[str]:
    source_names: set[str] = set()
    if records(data, "twenty_workspace_members"):
        source_names.add("twenty")
    if records(data, "slack_users"):
        source_names.add("slack")
    if any(
        records(data, key)
        for key in (
            "linear_users",
            "linear_teams",
            "linear_projects",
            "linear_issues",
            "linear_comments",
        )
    ):
        source_names.add("linear")
    return sorted(source_names)


def _employee_refs(employees: list[CatalogEmployee | None]) -> list[str]:
    refs: list[str] = []
    for employee in employees:
        if employee is not None and employee.entity_ref not in refs:
            refs.append(employee.entity_ref)
    return refs


def _source_imports(
    data: dict[str, object],
    *,
    catalog: SourceCatalog,
) -> dict[str, dict[str, str]]:
    imports: dict[str, dict[str, str]] = {}
    for member in records(data, "twenty_workspace_members"):
        source_id = _string_value(member.get("id"))
        if source_id is None:
            continue
        email = _string_value(member.get("email"))
        imports[f"twenty:workspaceMember:{source_id}"] = _compact_string_record(
            {
                "source": "twenty",
                "source_type": "workspace_member",
                "source_id": source_id,
                "display_name": member.get("display_name"),
                "email": member.get("email"),
                "entity_ref": f"employee:email:{email.lower()}" if email else None,
            }
        )
    for user in records(data, "slack_users"):
        source_id = _string_value(user.get("id"))
        if source_id is None:
            continue
        email = _string_value(user.get("email"))
        employee = catalog.employee_by_email.get(email.lower()) if email else None
        imports[f"slack:user:{source_id}"] = _compact_string_record(
            {
                "source": "slack",
                "source_type": "user",
                "source_id": source_id,
                "display_name": user.get("display_name"),
                "email": user.get("email"),
                "entity_ref": employee.entity_ref if employee is not None else None,
                "honcho_peer_id": f"slack_{source_id}" if employee is not None else None,
                "deleted": str(bool(user.get("deleted"))).lower(),
                "is_bot": str(bool(user.get("is_bot"))).lower(),
            }
        )
    for user in records(data, "linear_users"):
        source_id = _string_value(user.get("id"))
        if source_id is None:
            continue
        employee = catalog.employee_for_linear_user(source_id)
        imports[f"linear:user:{source_id}"] = _compact_string_record(
            {
                "source": "linear",
                "source_type": "user",
                "source_id": source_id,
                "display_name": user.get("display_name"),
                "email": user.get("email"),
                "entity_ref": employee.entity_ref if employee is not None else None,
            }
        )
    imports.update(
        _catalog_source_imports(
            catalog.linear_teams,
            source="linear",
            source_type="team",
        )
    )
    imports.update(
        _catalog_source_imports(
            catalog.linear_projects,
            source="linear",
            source_type="project",
        )
    )
    return dict(sorted(imports.items()))


def _catalog_source_imports(
    records_by_ref: dict[str, dict[str, object]],
    *,
    source: str,
    source_type: str,
) -> dict[str, dict[str, str]]:
    return {
        source_ref: _compact_string_record(
            {
                "source": source,
                "source_type": source_type,
                **{key: value for key, value in record.items() if key != "source_ref"},
            }
        )
        for source_ref, record in records_by_ref.items()
    }


def _compact_string_record(record: dict[str, object]) -> dict[str, str]:
    return {key: value for key, value in record.items() if isinstance(value, str) and value}


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _permission_metadata(record: dict[str, object]) -> dict[str, list[str]]:
    value = record.get("permission_refs")
    if not isinstance(value, list):
        return {}
    permission_refs = [item for item in value if isinstance(item, str) and item]
    return {"permission_refs": permission_refs} if permission_refs else {}
