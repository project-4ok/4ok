from __future__ import annotations

from typing import Any

from fourok.etl.extract.source_records import SourceIdentity, SourceRecord


def linear_user_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _required_string(record, "id", "Linear user record requires id")
    display_name = _first_string(record, "display_name", "displayName", "name") or source_id
    email = _first_string(record, "email") or ""
    identities = _email_identities(email, display_name)

    return SourceRecord(
        source_ref=f"linear:user:{source_id}",
        source_system="linear",
        source_id=source_id,
        record_type="person",
        title=display_name,
        body=_join_text(display_name, email, "employee"),
        occurred_at=_first_string(record, "created_at", "createdAt") or "",
        updated_at=_first_string(record, "updated_at", "updatedAt") or "",
        source_url=_first_string(record, "url", "source_url") or "",
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state="deleted" if record.get("active") is False else "active",
        metadata=_compact_metadata({"source_object_type": "user"}),
        raw=record,
        source_identities=tuple(identities),
    )


def linear_issue_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    identifier = _required_string(
        record,
        "identifier",
        "Linear issue record requires identifier",
    )
    title = _first_string(record, "title") or identifier
    team_id = _first_string(record, "team_id", "teamId")
    creator_id = _first_string(record, "creator_id", "creatorId")
    assignee_id = _first_string(record, "assignee_id", "assigneeId")

    return SourceRecord(
        source_ref=f"linear:issue:{identifier}",
        source_system="linear",
        source_id=identifier,
        record_type="work_item",
        title=title,
        body=_join_text(identifier, title, _first_string(record, "description")),
        occurred_at=_first_string(record, "created_at", "createdAt") or "",
        updated_at=_first_string(record, "updated_at", "updatedAt") or "",
        author_ref=creator_id or "",
        source_url=_first_string(record, "url", "source_url") or "",
        thread_ref=f"linear:issue:{identifier}",
        permission_refs=tuple(_permission_refs(record, team_id)),
        identity_refs=tuple(_identity_refs(creator_id, assignee_id)),
        lifecycle_state=_linear_lifecycle_state(record),
        metadata=_compact_metadata(
            {
                "assignee_id": assignee_id or "",
                "creator_id": creator_id or "",
                "source_object_type": "issue",
                "status": _first_string(record, "status", "state") or "",
                "team_id": team_id or "",
                "team_key": _first_string(record, "team_key", "teamKey") or "",
            }
        ),
        raw=record,
    )


def linear_comment_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _required_string(record, "id", "Linear comment record requires id")
    issue_identifier = _required_string(
        record,
        "issue_identifier",
        "Linear comment record requires issue_identifier",
    )
    body = _required_string(record, "body", "Linear comment record requires body")
    user_id = _first_string(record, "user_id", "userId") or ""

    return SourceRecord(
        source_ref=f"linear:comment:{source_id}",
        source_system="linear",
        source_id=source_id,
        record_type="message",
        title=f"Comment on {issue_identifier}",
        body=_join_text(issue_identifier, _first_string(record, "issue_title"), body),
        occurred_at=_first_string(record, "created_at", "createdAt") or "",
        updated_at=_first_string(record, "updated_at", "updatedAt") or "",
        author_ref=user_id,
        source_url=_first_string(record, "url", "source_url") or "",
        thread_ref=f"linear:issue:{issue_identifier}",
        permission_refs=tuple(_permission_refs(record, _first_string(record, "team_id", "teamId"))),
        identity_refs=tuple(_identity_refs(user_id)),
        lifecycle_state=_linear_lifecycle_state(record),
        metadata=_compact_metadata(
            {
                "issue_identifier": issue_identifier,
                "source_object_type": "comment",
                "user_id": user_id,
            }
        ),
        raw=record,
    )


def _required_string(record: dict[str, Any], key: str, message: str) -> str:
    value = _first_string(record, key)
    if value is None:
        raise ValueError(message)
    return value


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _join_text(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _permission_refs(record: dict[str, Any], team_id: str | None) -> list[str]:
    explicit = record.get("permission_refs")
    if isinstance(explicit, list):
        return [item for item in explicit if isinstance(item, str)]
    return [f"linear:team:{team_id}"] if team_id else []


def _identity_refs(*values: str | None) -> list[str]:
    return [value for value in values if value]


def _email_identities(email: str, display_name: str) -> list[SourceIdentity]:
    if not email:
        return []
    return [
        SourceIdentity(
            source_system="linear",
            identity_ref=f"linear:email:{email.strip().casefold()}",
            identity_type="email",
            value=email,
            display_name=display_name,
        )
    ]


def _linear_lifecycle_state(record: dict[str, Any]) -> str:
    if record.get("archived") is True or record.get("canceled") is True:
        return "deleted"
    explicit = _first_string(record, "lifecycle_state")
    if explicit in {"active", "restricted", "deleted"}:
        return explicit
    return "active"


def _compact_metadata(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}
