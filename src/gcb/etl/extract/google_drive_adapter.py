from __future__ import annotations

from typing import Any

from gcb.etl.extract.source_records import SourceIdentity, SourceRecord


def google_drive_file_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _required_string(record, "id", "Google Drive file record requires id")
    title = _first_string(record, "name", "title") or source_id
    body = _first_string(record, "text", "body", "plain_text", "description")
    metadata_only = not body

    identities = _owner_identities(record)
    permission_refs = _permission_refs(record)
    # The live Drive API credentials may list files the local operator can read
    # while omitting `permissions`/`owners` fields for those files. Treat that as
    # operator-scoped local access rather than marking the imported document as
    # permanently restricted and therefore unretrievable.
    if not permission_refs:
        permission_refs = ["operator"]
    mime_type = _first_string(record, "mimeType", "mime_type") or ""
    folder_refs = _string_list(record.get("parents", record.get("folder_refs", [])))
    parent_refs = _string_list(record.get("parent_refs", []))
    owner_refs = [identity.identity_ref for identity in identities]
    content_status = _first_string(record, "content_status") or (
        "metadata_only" if metadata_only else "extracted"
    )
    export_status = _first_string(record, "export_status") or (
        "not_exported" if metadata_only else "exported_text"
    )
    folder_path = _first_string(record, "folder_path") or ""
    source_ref = f"google_drive:file:{source_id}"
    if metadata_only:
        body = _metadata_only_body(
            title=title,
            mime_type=mime_type,
            owners=_owner_labels(record),
            folder_refs=folder_refs,
            folder_path=folder_path,
            web_link=_first_string(record, "webViewLink", "source_url", "url") or "",
            content_status=content_status,
            export_status=export_status,
        )

    return SourceRecord(
        source_ref=source_ref,
        source_system="google_drive",
        source_id=source_id,
        record_type="document",
        title=title,
        body=body,
        occurred_at=_first_string(record, "createdTime", "created_at") or "",
        updated_at=_first_string(record, "modifiedTime", "updated_at") or "",
        source_url=_first_string(record, "webViewLink", "source_url", "url") or "",
        permission_refs=tuple(permission_refs),
        permission_snapshot_status="current" if permission_refs else "missing",
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state="deleted" if record.get("trashed") is True else "active",
        metadata=_compact_metadata(
            {
                "content_status": content_status,
                "export_status": export_status,
                "file_id": source_id,
                "folder_path": folder_path,
                "folder_refs": folder_refs,
                "mime_type": mime_type,
                "owner_refs": owner_refs,
                "parent_refs": parent_refs,
                "raw_metadata_ref": source_ref,
                "source_object_type": "file",
            }
        ),
        raw=record,
        source_identities=tuple(identities),
    )


def _metadata_only_body(
    *,
    title: str,
    mime_type: str,
    owners: list[str],
    folder_refs: list[str],
    folder_path: str,
    web_link: str,
    content_status: str,
    export_status: str,
) -> str:
    lines = [
        "Google Drive metadata-only file",
        f"Name: {title}",
        f"MIME type: {mime_type}",
    ]
    if folder_path:
        lines.append(f"Folder path: {folder_path}")
    lines.extend(f"Owner: {owner}" for owner in owners)
    lines.extend(f"Folder: {folder_ref}" for folder_ref in folder_refs)
    if web_link:
        lines.append(f"Web link: {web_link}")
    lines.extend(
        [
            f"Content status: {content_status}",
            f"Export status: {export_status}",
        ]
    )
    return "\n".join(line for line in lines if line.strip())


def _owner_labels(record: dict[str, Any]) -> list[str]:
    labels = []
    owners = record.get("owners", [])
    if not isinstance(owners, list):
        return labels
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        email = _first_string(owner, "emailAddress", "email")
        display_name = _first_string(owner, "displayName", "name")
        if display_name and email:
            labels.append(f"{display_name} <{email}>")
        elif display_name:
            labels.append(display_name)
        elif email:
            labels.append(email)
    return labels


def _owner_identities(record: dict[str, Any]) -> list[SourceIdentity]:
    identities = []
    owners = record.get("owners", [])
    if not isinstance(owners, list):
        return identities
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        email = _first_string(owner, "emailAddress", "email")
        if not email:
            continue
        identities.append(
            SourceIdentity(
                source_system="google_drive",
                identity_ref=f"google_drive:email:{email.strip().casefold()}",
                identity_type="owner",
                value=email,
                display_name=_first_string(owner, "displayName", "name") or "",
            )
        )
    return _dedupe_identities(identities)


def _permission_refs(record: dict[str, Any]) -> list[str]:
    explicit = _string_list(record.get("permission_refs", []))
    if explicit:
        return _dedupe_strings(explicit)

    refs = []
    permissions = record.get("permissions", [])
    if not isinstance(permissions, list):
        return refs
    for permission in permissions:
        if not isinstance(permission, dict):
            continue
        permission_id = _first_string(permission, "id")
        if permission_id:
            refs.append(f"google_drive:permission:{permission_id}")
            continue
        permission_type = _first_string(permission, "type") or "unknown"
        email = _first_string(permission, "emailAddress", "email")
        if email:
            refs.append(f"google_drive:permission:{permission_type}:{email.strip().casefold()}")
            continue
        domain = _first_string(permission, "domain")
        if permission_type == "domain" and domain:
            refs.append(f"google_drive:permission:domain:{domain.strip().casefold()}")
            continue
        if permission_type == "anyone":
            refs.append("google_drive:permission:anyone")
    return _dedupe_strings(refs)


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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _dedupe_identities(identities: list[SourceIdentity]) -> list[SourceIdentity]:
    seen = set()
    deduped = []
    for identity in identities:
        key = (identity.identity_ref, identity.identity_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(identity)
    return deduped


def _compact_metadata(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value}
