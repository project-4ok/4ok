from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any, NotRequired, TypedDict

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.source_records import SourceRecord


class CanonicalObjectInput(TypedDict):
    object_ref: str
    object_type: str
    title: NotRequired[str]
    source_refs: NotRequired[tuple[str, ...]]
    metadata: NotRequired[dict[str, Any]]
    lifecycle_state: NotRequired[str]


class EntityLinkInput(TypedDict):
    link_ref: str
    source_ref: str
    object_ref: str
    relationship_type: str
    confidence: float
    evidence: NotRequired[dict[str, Any]]
    reason: NotRequired[str]
    status: NotRequired[str]


RECORD_TYPE_TO_OBJECT_TYPE = {
    "email": "Message",
    "message": "Message",
    "slack_message": "Message",
    "event": "Message",
    "document": "Document",
    "resource": "Document",
    "work_item": "WorkItem",
    "linear_issue": "WorkItem",
    "project": "WorkItem",
    "relationship": "Relationship",
    "person": "Person",
    "organization": "Organization",
    "company": "Organization",
}


def canonical_object_rows(engine: Engine, canonical_objects: Table) -> list[dict[str, object]]:
    statement = select(canonical_objects).order_by(canonical_objects.c.object_ref)
    with engine.connect() as connection:
        return [
            _serialize_canonical_object_row(dict(row))
            for row in connection.execute(statement).mappings()
        ]


def entity_link_rows(engine: Engine, entity_links: Table) -> list[dict[str, object]]:
    statement = select(entity_links).order_by(entity_links.c.link_ref)
    with engine.connect() as connection:
        return [
            _serialize_entity_link_row(dict(row))
            for row in connection.execute(statement).mappings()
        ]


def store_canonical_objects(
    engine: Engine,
    canonical_objects: Table,
    *,
    objects: list[CanonicalObjectInput],
) -> None:
    if not objects:
        return

    object_refs = [context_object["object_ref"] for context_object in objects]
    rows = [
        {
            "object_ref": context_object["object_ref"],
            "object_type": context_object["object_type"],
            "title": context_object.get("title", ""),
            "source_refs": _json_array(context_object.get("source_refs", ())),
            "metadata_json": context_object.get("metadata", {}),
            "lifecycle_state": context_object.get("lifecycle_state", "active"),
        }
        for context_object in objects
    ]
    with engine.begin() as connection:
        connection.execute(
            delete(canonical_objects).where(canonical_objects.c.object_ref.in_(object_refs))
        )
        connection.execute(insert(canonical_objects), rows)


def canonical_objects_from_source_records(
    records: list[SourceRecord],
) -> list[CanonicalObjectInput]:
    return [canonical_object_from_source_record(record) for record in records]


def canonical_object_from_source_record(record: SourceRecord) -> CanonicalObjectInput:
    return {
        "object_ref": record.source_ref,
        "object_type": object_type_for_record_type(record.record_type),
        "title": record.title,
        "source_refs": (record.source_ref,),
        "metadata": {
            **record.metadata,
            "record_type": record.record_type,
            "source_id": record.source_id,
            "source_system": record.source_system,
        },
        "lifecycle_state": record.effective_lifecycle_state,
    }


def object_type_for_record_type(record_type: str) -> str:
    return RECORD_TYPE_TO_OBJECT_TYPE.get(record_type, "Document")


def entity_links_from_source_records(records: list[SourceRecord]) -> list[EntityLinkInput]:
    person_by_source_id = {
        record.source_id: record
        for record in records
        if record.record_type == "person" and _employee_entity_ref(record)
    }
    record_by_source_ref = {record.source_ref: record for record in records}
    comments_by_thread_ref = _comments_by_thread_ref(records)
    links: list[EntityLinkInput] = []
    for record in records:
        for relationship_type, source_id in _source_identity_relationships(record):
            person = person_by_source_id.get(source_id)
            if person is None:
                continue
            _append_link(
                links,
                source_ref=record.source_ref,
                object_ref=person.source_ref,
                relationship_type=relationship_type,
                confidence=1.0,
                evidence={
                    "entity_ref": _employee_entity_ref(person),
                    "source_identity_ref": source_id,
                    "source_identity_field": relationship_type,
                },
                reason="deterministic_source_identity",
            )
        if record.record_type == "message" and record.thread_ref:
            parent = record_by_source_ref.get(record.thread_ref)
            if parent is not None and parent.source_ref != record.source_ref:
                _append_link(
                    links,
                    source_ref=record.source_ref,
                    object_ref=parent.source_ref,
                    relationship_type="parent_work_item",
                    confidence=1.0,
                    evidence={"thread_ref": record.thread_ref},
                    reason="deterministic_thread_ref",
                )
        for mention_link in _full_name_mention_links(record, person_by_source_id.values()):
            _append_link(
                links,
                source_ref=mention_link["source_ref"],
                object_ref=mention_link["object_ref"],
                relationship_type=mention_link["relationship_type"],
                confidence=mention_link["confidence"],
                evidence=mention_link["evidence"],
                reason=mention_link["reason"],
            )
        for comment in comments_by_thread_ref.get(record.source_ref, ()):
            commenter = person_by_source_id.get(comment.author_ref)
            if commenter is not None:
                _append_link(
                    links,
                    source_ref=record.source_ref,
                    object_ref=commenter.source_ref,
                    relationship_type="commenter",
                    confidence=1.0,
                    evidence={"comment_source_ref": comment.source_ref},
                    reason="deterministic_thread_comment_author",
                )
    for source_ref, object_ref, email in _same_email_identity_matches(records):
        _append_link(
            links,
            source_ref=source_ref,
            object_ref=object_ref,
            relationship_type="same_email_identity",
            confidence=1.0,
            evidence={"email": email},
            reason="exact_email_identity_match",
        )
    return _dedupe_links(links)


def store_entity_links(
    engine: Engine,
    entity_links: Table,
    *,
    links: list[EntityLinkInput],
) -> None:
    if not links:
        return

    link_refs = [link["link_ref"] for link in links]
    rows = [
        {
            "link_ref": link["link_ref"],
            "source_ref": link["source_ref"],
            "object_ref": link["object_ref"],
            "relationship_type": link["relationship_type"],
            "confidence": link["confidence"],
            "evidence_json": link.get("evidence", {}),
            "reason": link.get("reason", ""),
            "status": link.get("status", "candidate"),
        }
        for link in links
    ]
    with engine.begin() as connection:
        connection.execute(delete(entity_links).where(entity_links.c.link_ref.in_(link_refs)))
        connection.execute(insert(entity_links), rows)


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), sort_keys=True)


def _json_object(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True)


def _serialize_canonical_object_row(row: dict[str, object]) -> dict[str, object]:
    row["metadata_json"] = _json_object_string(row["metadata_json"])
    return row


def _serialize_entity_link_row(row: dict[str, object]) -> dict[str, object]:
    row["evidence_json"] = _json_object_string(row["evidence_json"])
    return row


def _json_object_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return "{}"


def _source_identity_relationships(record: SourceRecord) -> list[tuple[str, str]]:
    relationships = []
    if record.author_ref:
        relationships.append(("author", record.author_ref))
    assignee_id = record.metadata.get("assignee_id")
    if isinstance(assignee_id, str) and assignee_id:
        relationships.append(("assignee", assignee_id))
    user_id = record.metadata.get("user_id")
    if isinstance(user_id, str) and user_id and not record.author_ref:
        relationships.append(("author", user_id))
    return relationships


def _comments_by_thread_ref(records: list[SourceRecord]) -> dict[str, list[SourceRecord]]:
    comments_by_thread_ref: dict[str, list[SourceRecord]] = {}
    for record in records:
        if record.record_type != "message" or not record.thread_ref:
            continue
        comments_by_thread_ref.setdefault(record.thread_ref, []).append(record)
    return comments_by_thread_ref


def _full_name_mention_links(
    record: SourceRecord, people: Iterable[SourceRecord]
) -> list[dict[str, Any]]:
    if record.record_type == "person":
        return []
    links: list[dict[str, Any]] = []
    for person in people:
        if person.source_system != record.source_system:
            continue
        display_name = person.title.strip()
        if len(display_name.split()) < 2:
            continue
        match_field = _matching_text_field(record, display_name)
        if match_field is None:
            continue
        links.append(
            {
                "source_ref": record.source_ref,
                "object_ref": person.source_ref,
                "relationship_type": "mentioned_person",
                "confidence": 1.0,
                "evidence": {"matched_text": display_name, "match_field": match_field},
                "reason": "deterministic_full_name_mention",
            }
        )
    return links


def _matching_text_field(record: SourceRecord, text: str) -> str | None:
    pattern = re.compile(rf"(?<!\w){re.escape(text)}(?!\w)", re.IGNORECASE)
    for field, value in (("title", record.title), ("body", record.body)):
        if value and pattern.search(value):
            return field
    return None


def _same_email_identity_matches(records: list[SourceRecord]) -> list[tuple[str, str, str]]:
    people_by_email: dict[str, list[SourceRecord]] = {}
    for record in records:
        if record.record_type != "person":
            continue
        for email in _person_emails(record):
            people_by_email.setdefault(email, []).append(record)

    matches: list[tuple[str, str, str]] = []
    for email, people in people_by_email.items():
        for source in people:
            for target in people:
                if source.source_ref == target.source_ref:
                    continue
                if source.source_system == target.source_system:
                    continue
                matches.append((source.source_ref, target.source_ref, email))
    return matches


def _person_emails(record: SourceRecord) -> list[str]:
    emails = []
    for identity in record.source_identities:
        if identity.identity_type == "email" and identity.value:
            emails.append(identity.value.strip().casefold())
    return sorted(set(emails))


def _append_link(
    links: list[EntityLinkInput],
    *,
    source_ref: str,
    object_ref: str,
    relationship_type: str,
    confidence: float,
    evidence: dict[str, Any],
    reason: str,
) -> None:
    links.append(
        {
            "link_ref": f"{source_ref}->{object_ref}:{relationship_type}",
            "source_ref": source_ref,
            "object_ref": object_ref,
            "relationship_type": relationship_type,
            "confidence": confidence,
            "evidence": evidence,
            "reason": reason,
            "status": "linked",
        }
    )


def _dedupe_links(links: list[EntityLinkInput]) -> list[EntityLinkInput]:
    deduped: dict[str, EntityLinkInput] = {}
    for link in links:
        deduped.setdefault(link["link_ref"], link)
    return list(deduped.values())


def _employee_entity_ref(record: SourceRecord) -> str:
    for identity in record.source_identities:
        if identity.identity_type == "email" and identity.value:
            return f"employee:email:{identity.value.lower()}"
    return ""
