from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.etl.load.context_objects import (
    canonical_object_from_source_record,
    canonical_object_rows,
    entity_link_rows,
    entity_links_from_source_records,
    object_type_for_record_type,
    store_canonical_objects,
    store_entity_links,
)
from fourok.governance.state import create_governed_context_state


def test_store_canonical_objects_replaces_rows_by_object_ref() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    first = {
        "object_ref": "linear:issue:OPS-1",
        "object_type": "WorkItem",
        "title": "Ask Robin to move meeting",
        "source_refs": ("linear:issue:OPS-1",),
        "metadata": {"status": "open"},
        "lifecycle_state": "active",
    }
    replacement = {
        "object_ref": "linear:issue:OPS-1",
        "object_type": "WorkItem",
        "title": "Move Robin meeting",
        "source_refs": ("linear:issue:OPS-1", "linear:comment:99"),
        "metadata": {"status": "triaged"},
        "lifecycle_state": "active",
    }

    store_canonical_objects(state.engine, state.canonical_objects, objects=[first])
    store_canonical_objects(state.engine, state.canonical_objects, objects=[replacement])

    assert canonical_object_rows(state.engine, state.canonical_objects) == [
        {
            "object_ref": "linear:issue:OPS-1",
            "object_type": "WorkItem",
            "title": "Move Robin meeting",
            "source_refs": '["linear:issue:OPS-1", "linear:comment:99"]',
            "metadata_json": '{"status": "triaged"}',
            "lifecycle_state": "active",
        }
    ]


def test_store_entity_links_preserves_evidence_reason_confidence_and_status() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    link = {
        "link_ref": "linear:issue:OPS-1->twenty:person:robin",
        "source_ref": "linear:issue:OPS-1",
        "object_ref": "twenty:person:robin",
        "relationship_type": "mentioned_person",
        "confidence": 0.86,
        "evidence": {"matched_text": "robin", "candidate": "Robin Scharf"},
        "reason": "text_alias_match",
        "status": "candidate",
    }

    store_entity_links(state.engine, state.entity_links, links=[link])

    assert entity_link_rows(state.engine, state.entity_links) == [
        {
            "link_ref": "linear:issue:OPS-1->twenty:person:robin",
            "source_ref": "linear:issue:OPS-1",
            "object_ref": "twenty:person:robin",
            "relationship_type": "mentioned_person",
            "confidence": 0.86,
            "evidence_json": '{"candidate": "Robin Scharf", "matched_text": "robin"}',
            "reason": "text_alias_match",
            "status": "candidate",
        }
    ]


def test_source_records_map_to_canonical_object_types() -> None:
    assert object_type_for_record_type("person") == "Person"
    assert object_type_for_record_type("organization") == "Organization"
    assert object_type_for_record_type("company") == "Organization"
    assert object_type_for_record_type("email") == "Message"
    assert object_type_for_record_type("message") == "Message"
    assert object_type_for_record_type("event") == "Message"
    assert object_type_for_record_type("document") == "Document"
    assert object_type_for_record_type("resource") == "Document"
    assert object_type_for_record_type("work_item") == "WorkItem"
    assert object_type_for_record_type("project") == "WorkItem"
    assert object_type_for_record_type("relationship") == "Relationship"
    assert object_type_for_record_type("unknown") == "Document"


def test_canonical_object_preserves_source_record_metadata() -> None:
    context_object = canonical_object_from_source_record(
        SourceRecord(
            source_ref="linear:issue:OPS-1",
            source_system="linear",
            source_id="OPS-1",
            record_type="work_item",
            title="Ask Robin",
            body="Ask Robin to move meeting.",
            metadata={"status": "open"},
            lifecycle_state="restricted",
        )
    )

    assert context_object == {
        "object_ref": "linear:issue:OPS-1",
        "object_type": "WorkItem",
        "title": "Ask Robin",
        "source_refs": ("linear:issue:OPS-1",),
        "metadata": {
            "record_type": "work_item",
            "source_id": "OPS-1",
            "source_system": "linear",
            "status": "open",
        },
        "lifecycle_state": "restricted",
    }


def test_entity_links_include_thread_commenters_and_full_name_mentions() -> None:
    records = [
        _person_record(
            source_ref="linear:user:olivia",
            source_system="linear",
            source_id="olivia",
            title="Olivia Smith",
            email="olivia@example.com",
        ),
        _person_record(
            source_ref="linear:user:robin",
            source_system="linear",
            source_id="robin",
            title="Robin Scharf",
            email="robin@example.com",
        ),
        SourceRecord(
            source_ref="linear:issue:OPS-1",
            source_system="linear",
            source_id="OPS-1",
            record_type="work_item",
            title="Ask Robin Scharf to move the meeting",
            body="Olivia Smith needs Robin Scharf to move the renewal meeting.",
            author_ref="olivia",
            thread_ref="linear:issue:OPS-1",
        ),
        SourceRecord(
            source_ref="linear:comment:comment-1",
            source_system="linear",
            source_id="comment-1",
            record_type="message",
            title="Comment on OPS-1",
            body="Robin Scharf confirmed the meeting can move.",
            author_ref="olivia",
            thread_ref="linear:issue:OPS-1",
        ),
    ]

    links = _links_by_ref(entity_links_from_source_records(records))

    assert (
        links["linear:comment:comment-1->linear:issue:OPS-1:parent_work_item"]["relationship_type"]
        == "parent_work_item"
    )
    assert (
        links["linear:issue:OPS-1->linear:user:olivia:commenter"]["relationship_type"]
        == "commenter"
    )
    assert (
        links["linear:issue:OPS-1->linear:user:robin:mentioned_person"].get("reason")
        == "deterministic_full_name_mention"
    )
    assert links["linear:comment:comment-1->linear:user:robin:mentioned_person"].get(
        "evidence"
    ) == {"matched_text": "Robin Scharf", "match_field": "body"}


def test_entity_links_include_cross_source_exact_email_identity_matches() -> None:
    records = [
        _person_record(
            source_ref="twenty:person:olivia",
            source_system="twenty",
            source_id="twenty-olivia",
            title="Olivia Smith",
            email="olivia@example.com",
        ),
        _person_record(
            source_ref="linear:user:olivia",
            source_system="linear",
            source_id="linear-olivia",
            title="Olivia Smith",
            email="olivia@example.com",
        ),
        _person_record(
            source_ref="linear:user:other",
            source_system="linear",
            source_id="linear-other",
            title="Other Person",
            email="other@example.com",
        ),
    ]

    links = _links_by_ref(entity_links_from_source_records(records))

    assert links["twenty:person:olivia->linear:user:olivia:same_email_identity"] == {
        "link_ref": "twenty:person:olivia->linear:user:olivia:same_email_identity",
        "source_ref": "twenty:person:olivia",
        "object_ref": "linear:user:olivia",
        "relationship_type": "same_email_identity",
        "confidence": 1.0,
        "evidence": {"email": "olivia@example.com"},
        "reason": "exact_email_identity_match",
        "status": "linked",
    }


def _person_record(
    *, source_ref: str, source_system: str, source_id: str, title: str, email: str
) -> SourceRecord:
    return SourceRecord(
        source_ref=source_ref,
        source_system=source_system,
        source_id=source_id,
        record_type="person",
        title=title,
        body=f"{title} {email}",
        identity_refs=(f"{source_system}:email:{email}",),
        source_identities=(
            SourceIdentity(
                source_system=source_system,
                identity_ref=f"{source_system}:email:{email}",
                identity_type="email",
                value=email,
                display_name=title,
            ),
        ),
    )


def _links_by_ref(links):
    return {link["link_ref"]: link for link in links}
