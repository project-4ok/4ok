from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.load.context_objects import (
    canonical_object_from_source_record,
    canonical_object_rows,
    entity_link_rows,
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
