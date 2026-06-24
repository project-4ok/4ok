from pathlib import Path

from fourok.honcho.catalog import CatalogEmployee
from fourok.honcho.state import HonchoSyncState


def test_honcho_sync_state_records_write_receipts_by_source_ref(tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state = HonchoSyncState.load(state_path)

    state.record_write_receipt(
        source_ref="linear:issue:ABC-123",
        honcho_message_id="msg-123",
        honcho_peer_id="slack_U123456",
        honcho_session_id="slack_U123456:linear:2026-06",
        rule_version="linear_assignee_employee_match_v1",
        routing_confidence="high",
        employee_peer="employee:email:olivia@example.com",
        candidate_entities="employee:email:olivia@example.com",
        aggregate_fallback_peer="linear:team:ops",
        source_url="https://linear.app/acme/issue/ABC-123",
        source_updated_at="2026-06-01T10:15:00+00:00",
        written_at="2026-06-01T10:20:00+00:00",
    )
    state.set_checkpoint("linear", "2026-06-01T10:15:00+00:00")
    state.save()

    reloaded = HonchoSyncState.load(state_path)
    assert reloaded.is_imported("linear:issue:ABC-123") is True
    assert reloaded.imported_source_refs() == ["linear:issue:ABC-123"]
    assert reloaded.connector_checkpoint("linear") == "2026-06-01T10:15:00+00:00"
    assert reloaded.to_dict()["source_refs"]["linear:issue:ABC-123"] == {
        "honcho_message_id": "msg-123",
        "honcho_peer_id": "slack_U123456",
        "honcho_session_id": "slack_U123456:linear:2026-06",
        "rule_version": "linear_assignee_employee_match_v1",
        "routing_confidence": "high",
        "employee_peer": "employee:email:olivia@example.com",
        "candidate_entities": "employee:email:olivia@example.com",
        "aggregate_fallback_peer": "linear:team:ops",
        "source_url": "https://linear.app/acme/issue/ABC-123",
        "source_updated_at": "2026-06-01T10:15:00+00:00",
        "written_at": "2026-06-01T10:20:00+00:00",
    }


def test_honcho_sync_state_returns_source_receipt_copy(tmp_path: Path) -> None:
    state = HonchoSyncState.load(tmp_path / "honcho-sync-state.json")
    state.record_write_receipt(
        source_ref="linear:issue:ABC-123",
        honcho_message_id="msg-123",
        honcho_peer_id="slack_U123456",
        honcho_session_id="slack_U123456:linear:2026-06",
        rule_version="linear_assignee_employee_match_v1",
        routing_confidence="high",
        employee_peer="employee:email:olivia@example.com",
        candidate_entities="employee:email:olivia@example.com",
        aggregate_fallback_peer="linear:team:ops",
        source_url="https://linear.app/acme/issue/ABC-123",
        source_updated_at="2026-06-01T10:15:00+00:00",
        written_at="2026-06-01T10:20:00+00:00",
    )

    receipt = state.source_receipt("linear:issue:ABC-123")

    assert receipt == {
        "honcho_message_id": "msg-123",
        "honcho_peer_id": "slack_U123456",
        "honcho_session_id": "slack_U123456:linear:2026-06",
        "rule_version": "linear_assignee_employee_match_v1",
        "routing_confidence": "high",
        "employee_peer": "employee:email:olivia@example.com",
        "candidate_entities": "employee:email:olivia@example.com",
        "aggregate_fallback_peer": "linear:team:ops",
        "source_url": "https://linear.app/acme/issue/ABC-123",
        "source_updated_at": "2026-06-01T10:15:00+00:00",
        "written_at": "2026-06-01T10:20:00+00:00",
    }
    assert receipt is not state.source_refs["linear:issue:ABC-123"]
    assert state.source_receipt("linear:issue:missing") is None


def test_honcho_sync_state_classifies_changed_source_refs(tmp_path: Path) -> None:
    state = HonchoSyncState.load(tmp_path / "honcho-sync-state.json")
    state.record_write_receipt(
        source_ref="linear:issue:ABC-123",
        honcho_message_id="msg-123",
        honcho_peer_id="slack_U123456",
        honcho_session_id="slack_U123456:linear:2026-06",
        rule_version="linear_assignee_employee_match_v1",
        routing_confidence="high",
        employee_peer="employee:email:olivia@example.com",
        candidate_entities="employee:email:olivia@example.com",
        aggregate_fallback_peer="linear:team:ops",
        source_url="https://linear.app/acme/issue/ABC-123",
        source_updated_at="2026-06-01T10:15:00+00:00",
        written_at="2026-06-01T10:20:00+00:00",
    )

    assert state.classify_message_source_refs(
        [
            {
                "source_ref": "linear:issue:ABC-123",
                "source_updated_at": "2026-06-01T10:25:00+00:00",
            },
            {
                "source_ref": "linear:issue:DEF-456",
                "source_updated_at": "2026-06-01T10:30:00+00:00",
            },
        ]
    ) == {
        "new_source_refs": ["linear:issue:DEF-456"],
        "changed_source_refs": ["linear:issue:ABC-123"],
        "skipped_source_refs": [],
    }


def test_honcho_sync_state_round_trips_employee_catalog(tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state = HonchoSyncState.load(state_path)

    state.record_employee_catalog(
        {
            "employee:email:olivia@example.com": CatalogEmployee(
                entity_ref="employee:email:olivia@example.com",
                display_name="Olivia Smith",
                primary_email="olivia@example.com",
                honcho_peer_id="slack_U123456",
                source_identities=[
                    "twenty:workspaceMember:twenty-member-olivia",
                    "slack:user:U123456",
                    "linear:user:linear-user-olivia",
                ],
            )
        }
    )
    state.save()

    reloaded = HonchoSyncState.load(state_path)
    assert reloaded.employee_catalog()["employee:email:olivia@example.com"].to_dict() == {
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


def test_honcho_sync_state_round_trips_linear_catalog_records(tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state = HonchoSyncState.load(state_path)

    state.record_linear_catalogs(
        teams={
            "linear:team:ops": {
                "source_ref": "linear:team:ops",
                "source_id": "ops",
                "key": "OPS",
                "name": "Operations",
            }
        },
        projects={
            "linear:project:project-meetings": {
                "source_ref": "linear:project:project-meetings",
                "source_id": "project-meetings",
                "name": "Meeting Operations",
            }
        },
    )
    state.save()

    reloaded = HonchoSyncState.load(state_path)
    assert reloaded.linear_teams == {
        "linear:team:ops": {
            "source_ref": "linear:team:ops",
            "source_id": "ops",
            "key": "OPS",
            "name": "Operations",
        }
    }
    assert reloaded.linear_projects == {
        "linear:project:project-meetings": {
            "source_ref": "linear:project:project-meetings",
            "source_id": "project-meetings",
            "name": "Meeting Operations",
        }
    }


def test_honcho_sync_state_round_trips_source_import_records(tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state = HonchoSyncState.load(state_path)

    state.record_source_imports(
        {
            "slack:user:U123456": {
                "source": "slack",
                "source_type": "user",
                "source_id": "U123456",
                "entity_ref": "employee:email:olivia@example.com",
            }
        },
        imported_at="2026-06-01T10:20:00+00:00",
    )
    state.save()

    reloaded = HonchoSyncState.load(state_path)
    assert reloaded.source_imports == {
        "slack:user:U123456": {
            "source": "slack",
            "source_type": "user",
            "source_id": "U123456",
            "entity_ref": "employee:email:olivia@example.com",
            "imported_at": "2026-06-01T10:20:00+00:00",
        }
    }
    assert reloaded.to_dict()["source_imports"] == reloaded.source_imports


def test_honcho_sync_state_round_trips_sync_metadata(tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state = HonchoSyncState.load(state_path)

    state.record_successful_sync("linear", "2026-06-01T10:20:00+00:00")
    state.set_catalog_updated_at("employees", "2026-06-01T10:20:00+00:00")
    state.save()

    reloaded = HonchoSyncState.load(state_path)
    assert reloaded.last_successful_sync("linear") == "2026-06-01T10:20:00+00:00"
    assert reloaded.catalog_updated_at("employees") == "2026-06-01T10:20:00+00:00"
    assert reloaded.to_dict()["last_successful_syncs"] == {"linear": "2026-06-01T10:20:00+00:00"}
    assert reloaded.to_dict()["catalog_updated_at"] == {"employees": "2026-06-01T10:20:00+00:00"}
