from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gcb.etl.extract.source_records import SourceIdentity, SourceRecord


def load_context_snapshot_source_records(fixture_path: Path) -> list[SourceRecord]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("context snapshot fixture must contain a JSON object")
    return context_snapshot_source_records(data)


def context_snapshot_source_records(data: dict[str, Any]) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    records.extend(_twenty_workspace_members(_list(data, "twenty_workspace_members")))
    records.extend(_slack_users(_list(data, "slack_users")))
    records.extend(_linear_users(_list(data, "linear_users")))
    records.extend(_linear_teams(_list(data, "linear_teams")))
    records.extend(_linear_projects(_list(data, "linear_projects")))
    records.extend(_linear_issues(_list(data, "linear_issues")))
    records.extend(_linear_comments(_list(data, "linear_comments")))
    return records


def _twenty_workspace_members(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"twenty:workspaceMember:{_required_string(row, 'id')}",
            source_system="twenty",
            source_id=_required_string(row, "id"),
            record_type="person",
            title=_optional_string(row.get("display_name")),
            body=_person_body(row),
            identity_refs=_email_identity_refs("twenty", row),
            metadata=_metadata(row, source_object_type="workspace_member"),
            raw=row,
            source_identities=tuple(_email_identities("twenty", row)),
        )
        for row in rows
    ]


def _slack_users(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"slack:user:{_required_string(row, 'id')}",
            source_system="slack",
            source_id=_required_string(row, "id"),
            record_type="person",
            title=_optional_string(row.get("display_name")),
            body=_person_body(row),
            identity_refs=_email_identity_refs("slack", row),
            lifecycle_state="deleted" if row.get("deleted") is True else "active",
            metadata=_metadata(row, source_object_type="user"),
            raw=row,
            source_identities=tuple(_email_identities("slack", row)),
        )
        for row in rows
        if row.get("is_bot") is not True
    ]


def _linear_users(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"linear:user:{_required_string(row, 'id')}",
            source_system="linear",
            source_id=_required_string(row, "id"),
            record_type="person",
            title=_optional_string(row.get("display_name")),
            body=_person_body(row),
            identity_refs=_email_identity_refs("linear", row),
            metadata=_metadata(row, source_object_type="user"),
            raw=row,
            source_identities=tuple(_email_identities("linear", row)),
        )
        for row in rows
    ]


def _linear_teams(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"linear:team:{_required_string(row, 'id')}",
            source_system="linear",
            source_id=_required_string(row, "id"),
            record_type="resource",
            title=f"{_optional_string(row.get('name'))} {_optional_string(row.get('key'))}".strip(),
            body=_join_text(row.get("name"), row.get("key"), "team"),
            metadata=_metadata(row, source_object_type="team"),
            raw=row,
        )
        for row in rows
    ]


def _linear_projects(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"linear:project:{_required_string(row, 'id')}",
            source_system="linear",
            source_id=_required_string(row, "id"),
            record_type="project",
            title=_optional_string(row.get("name")),
            body=_join_text(row.get("name"), "project"),
            metadata=_metadata(row, source_object_type="project"),
            raw=row,
        )
        for row in rows
    ]


def _linear_issues(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"linear:issue:{_required_string(row, 'identifier')}",
            source_system="linear",
            source_id=_required_string(row, "identifier"),
            record_type="work_item",
            title=_optional_string(row.get("title")),
            body=_join_text(row.get("identifier"), row.get("title"), row.get("description")),
            occurred_at=_optional_string(row.get("created_at")),
            updated_at=_optional_string(row.get("updated_at")),
            author_ref=_optional_string(row.get("creator_id")),
            source_url=_optional_string(row.get("url")),
            thread_ref=f"linear:issue:{_required_string(row, 'identifier')}",
            permission_refs=tuple(_permission_refs(row)),
            identity_refs=tuple(_identity_refs(row, "creator_id", "assignee_id")),
            metadata=_metadata(row, source_object_type="issue"),
            raw=row,
        )
        for row in rows
    ]


def _linear_comments(rows: list[dict[str, Any]]) -> list[SourceRecord]:
    return [
        SourceRecord(
            source_ref=f"linear:comment:{_required_string(row, 'id')}",
            source_system="linear",
            source_id=_required_string(row, "id"),
            record_type="message",
            title=f"Comment on {_optional_string(row.get('issue_identifier'))}".strip(),
            body=_join_text(row.get("issue_identifier"), row.get("issue_title"), row.get("body")),
            occurred_at=_optional_string(row.get("created_at")),
            updated_at=_optional_string(row.get("updated_at")),
            author_ref=_optional_string(row.get("user_id")),
            source_url=_optional_string(row.get("url")),
            thread_ref=f"linear:issue:{_optional_string(row.get('issue_identifier'))}",
            permission_refs=tuple(_permission_refs(row)),
            identity_refs=tuple(_identity_refs(row, "user_id")),
            metadata=_metadata(row, source_object_type="comment"),
            raw=row,
        )
        for row in rows
    ]


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"context snapshot field must be a list: {key}")
    return [item for item in value if isinstance(item, dict)]


def _required_string(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"context snapshot row requires string field: {key}")
    return value


def _optional_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _join_text(*parts: Any) -> str:
    return " ".join(part for part in (_optional_string(value) for value in parts) if part)


def _person_body(row: dict[str, Any]) -> str:
    return _join_text(row.get("display_name"), row.get("email"), "employee")


def _permission_refs(row: dict[str, Any]) -> list[str]:
    value = row.get("permission_refs")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    team_id = _optional_string(row.get("team_id"))
    return [f"linear:team:{team_id}"] if team_id else []


def _identity_refs(row: dict[str, Any], *keys: str) -> list[str]:
    return [value for key in keys if isinstance((value := row.get(key)), str) and value]


def _email_identity_refs(source_system: str, row: dict[str, Any]) -> tuple[str, ...]:
    email = _optional_string(row.get("email"))
    if not email:
        return ()
    return (f"{source_system}:email:{email.lower()}",)


def _email_identities(source_system: str, row: dict[str, Any]) -> list[SourceIdentity]:
    email = _optional_string(row.get("email"))
    if not email:
        return []
    return [
        SourceIdentity(
            source_system=source_system,
            identity_ref=f"{source_system}:email:{email.lower()}",
            identity_type="email",
            value=email,
            display_name=_optional_string(row.get("display_name")),
        )
    ]


def _metadata(row: dict[str, Any], *, source_object_type: str) -> dict[str, Any]:
    return {**row, "source_object_type": source_object_type}
