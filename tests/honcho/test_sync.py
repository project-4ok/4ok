import json
from pathlib import Path

from fourok.honcho.experiment import build_honcho_sync_plan
from fourok.honcho.state import HonchoSyncState
from fourok.honcho.sync import execute_honcho_sync

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures" / "honcho" / "linear_twenty_slack_sample.json"
)


def test_execute_honcho_sync_writes_new_messages_and_records_receipts(tmp_path: Path) -> None:
    plan = build_honcho_sync_plan(json.loads(FIXTURE.read_text(encoding="utf-8")))
    state = HonchoSyncState.load(tmp_path / "honcho-sync-state.json")
    client = FakeHonchoClient()

    report = execute_honcho_sync(
        plan,
        state=state,
        client=client,
        synced_at="2026-06-01T10:20:00+00:00",
    )

    assert report == {
        "status": "ok",
        "summary": plan.summary,
        "written_source_refs": ["linear:issue:ABC-123"],
        "changed_source_refs": [],
        "skipped_source_refs": [],
        "written_messages": 1,
        "skipped_messages": 0,
    }
    assert client.messages == [plan.messages[0]]
    assert state.is_imported("linear:issue:ABC-123") is True
    assert state.to_dict()["source_refs"]["linear:issue:ABC-123"] == {
        "honcho_message_id": "msg-1",
        "honcho_peer_id": "slack_U123456",
        "honcho_session_id": "slack_U123456:linear:2026-06",
        "rule_version": "linear_assignee_employee_match_v1",
        "routing_confidence": "high",
        "employee_peer": "employee:email:olivia@example.com",
        "candidate_entities": "employee:email:olivia@example.com",
        "aggregate_fallback_peer": "linear:team:ops",
        "source_url": "https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
        "source_updated_at": "2026-06-01T10:15:00+00:00",
        "written_at": "2026-06-01T10:20:00+00:00",
    }
    assert state.connector_checkpoint("linear") == "2026-06-01T10:15:00+00:00"
    assert state.last_successful_sync("linear") == "2026-06-01T10:20:00+00:00"
    assert state.catalog_updated_at("employees") == "2026-06-01T10:20:00+00:00"
    assert state.linear_teams == {
        "linear:team:ops": {
            "source_ref": "linear:team:ops",
            "source_id": "ops",
            "key": "OPS",
            "name": "Operations",
        }
    }
    assert state.linear_projects == {
        "linear:project:project-meetings": {
            "source_ref": "linear:project:project-meetings",
            "source_id": "project-meetings",
            "name": "Meeting Operations",
        }
    }
    assert state.source_imports["slack:user:U123456"] == {
        "source": "slack",
        "source_type": "user",
        "source_id": "U123456",
        "display_name": "Olivia Smith",
        "email": "olivia@example.com",
        "entity_ref": "employee:email:olivia@example.com",
        "honcho_peer_id": "slack_U123456",
        "deleted": "false",
        "is_bot": "false",
        "imported_at": "2026-06-01T10:20:00+00:00",
    }
    assert sorted(state.source_imports) == [
        "linear:project:project-meetings",
        "linear:team:ops",
        "linear:user:linear-user-olivia",
        "slack:user:U123456",
        "twenty:workspaceMember:twenty-member-olivia",
    ]


def test_execute_honcho_sync_skips_already_imported_source_refs(tmp_path: Path) -> None:
    plan = build_honcho_sync_plan(json.loads(FIXTURE.read_text(encoding="utf-8")))
    state = HonchoSyncState.load(tmp_path / "honcho-sync-state.json")
    state.record_write_receipt(
        source_ref="linear:issue:ABC-123",
        honcho_message_id="msg-old",
        honcho_peer_id="slack_U123456",
        honcho_session_id="slack_U123456:linear:2026-06",
        rule_version="linear_assignee_employee_match_v1",
        routing_confidence="high",
        employee_peer="employee:email:olivia@example.com",
        candidate_entities="employee:email:olivia@example.com",
        aggregate_fallback_peer="linear:team:ops",
        source_url="https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
        source_updated_at="2026-06-01T10:15:00+00:00",
        written_at="2026-06-01T10:20:00+00:00",
    )
    client = FakeHonchoClient()

    report = execute_honcho_sync(plan, state=state, client=client)

    assert report["written_source_refs"] == []
    assert report["changed_source_refs"] == []
    assert report["skipped_source_refs"] == ["linear:issue:ABC-123"]
    assert client.messages == []


def test_execute_honcho_sync_writes_changed_source_refs_as_superseding_events(
    tmp_path: Path,
) -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"][0]["updated_at"] = "2026-06-01T10:25:00+00:00"
    plan = build_honcho_sync_plan(data)
    state = HonchoSyncState.load(tmp_path / "honcho-sync-state.json")
    state.record_write_receipt(
        source_ref="linear:issue:ABC-123",
        honcho_message_id="msg-old",
        honcho_peer_id="slack_U123456",
        honcho_session_id="slack_U123456:linear:2026-06",
        rule_version="linear_assignee_employee_match_v1",
        routing_confidence="high",
        employee_peer="employee:email:olivia@example.com",
        candidate_entities="employee:email:olivia@example.com",
        aggregate_fallback_peer="linear:team:ops",
        source_url="https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
        source_updated_at="2026-06-01T10:15:00+00:00",
        written_at="2026-06-01T10:20:00+00:00",
    )
    client = FakeHonchoClient()

    report = execute_honcho_sync(
        plan,
        state=state,
        client=client,
        synced_at="2026-06-01T10:30:00+00:00",
    )

    assert report["written_source_refs"] == ["linear:issue:ABC-123"]
    assert report["changed_source_refs"] == ["linear:issue:ABC-123"]
    assert report["skipped_source_refs"] == []
    assert report["written_messages"] == 1
    assert len(client.messages) == 1
    written_message = client.messages[0]
    assert written_message.peer == plan.messages[0].peer
    assert written_message.session == plan.messages[0].session
    assert written_message.text == plan.messages[0].text
    assert written_message.metadata["source_change"] == "changed"
    assert written_message.metadata["supersedes_honcho_message_id"] == "msg-old"
    assert client.metadata_updates == [
        {
            "session_id": "slack_U123456:linear:2026-06",
            "message_id": "msg-old",
            "metadata": {
                "source_ref": "linear:issue:ABC-123",
                "source_status": "superseded",
                "source_updated_at": "2026-06-01T10:15:00+00:00",
                "superseded_by_honcho_message_id": "msg-1",
                "superseded_by_source_updated_at": "2026-06-01T10:25:00+00:00",
            },
        }
    ]
    assert state.to_dict()["source_refs"]["linear:issue:ABC-123"] == {
        "honcho_message_id": "msg-1",
        "honcho_peer_id": "slack_U123456",
        "honcho_session_id": "slack_U123456:linear:2026-06",
        "rule_version": "linear_assignee_employee_match_v1",
        "routing_confidence": "high",
        "employee_peer": "employee:email:olivia@example.com",
        "candidate_entities": "employee:email:olivia@example.com",
        "aggregate_fallback_peer": "linear:team:ops",
        "source_url": "https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
        "source_updated_at": "2026-06-01T10:25:00+00:00",
        "written_at": "2026-06-01T10:30:00+00:00",
        "supersedes_honcho_message_id": "msg-old",
        "supersedes_source_updated_at": "2026-06-01T10:15:00+00:00",
    }

    rerun_report = execute_honcho_sync(plan, state=state, client=client)

    assert rerun_report["written_source_refs"] == []
    assert rerun_report["changed_source_refs"] == []
    assert rerun_report["skipped_source_refs"] == ["linear:issue:ABC-123"]
    assert len(client.messages) == 1


def test_execute_honcho_sync_persists_receipts_after_each_successful_write(
    tmp_path: Path,
) -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_comments"] = [
        {
            "id": "linear-comment-1",
            "body": "Robin can move the meeting to Thursday.",
            "url": "https://linear.app/acme/issue/ABC-123#comment-1",
            "issue_id": "linear-issue-abc-123",
            "issue_identifier": "ABC-123",
            "issue_title": "ask Robin to move meeting",
            "team_id": "ops",
            "created_at": "2026-06-01T10:30:00+00:00",
            "updated_at": "2026-06-01T10:35:00+00:00",
            "user_id": "linear-user-olivia",
        }
    ]
    plan = build_honcho_sync_plan(data)
    state_path = tmp_path / "honcho-sync-state.json"
    state = HonchoSyncState.load(state_path)

    try:
        execute_honcho_sync(plan, state=state, client=FailAfterFirstHonchoClient())
    except OSError as exc:
        assert str(exc) == "second write failed"
    else:
        raise AssertionError("expected second Honcho write to fail")

    reloaded = HonchoSyncState.load(state_path)
    assert reloaded.is_imported("linear:issue:ABC-123") is True
    assert reloaded.is_imported("linear:comment:linear-comment-1") is False


def test_execute_honcho_sync_records_catalog_only_success_metadata(tmp_path: Path) -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"] = []
    data["linear_comments"] = []
    plan = build_honcho_sync_plan(data)
    state = HonchoSyncState.load(tmp_path / "honcho-sync-state.json")
    client = FakeHonchoClient()

    report = execute_honcho_sync(
        plan,
        state=state,
        client=client,
        synced_at="2026-06-01T10:20:00+00:00",
    )

    assert report["written_messages"] == 0
    assert client.messages == []
    assert state.last_successful_sync("linear") == "2026-06-01T10:20:00+00:00"
    assert state.last_successful_sync("slack") == "2026-06-01T10:20:00+00:00"
    assert state.last_successful_sync("twenty") == "2026-06-01T10:20:00+00:00"
    assert state.catalog_updated_at("employees") == "2026-06-01T10:20:00+00:00"
    assert state.catalog_updated_at("linear_teams") == "2026-06-01T10:20:00+00:00"
    assert state.catalog_updated_at("linear_projects") == "2026-06-01T10:20:00+00:00"


class FakeHonchoClient:
    def __init__(self) -> None:
        self.messages = []
        self.metadata_updates = []

    def add_message(self, message):
        self.messages.append(message)
        return [{"id": f"msg-{len(self.messages)}"}]

    def update_message_metadata(self, *, session_id, message_id, metadata):
        self.metadata_updates.append(
            {"session_id": session_id, "message_id": message_id, "metadata": metadata}
        )
        return {"id": message_id, "metadata": metadata}


class FailAfterFirstHonchoClient:
    def __init__(self) -> None:
        self.messages = []

    def add_message(self, message):
        self.messages.append(message)
        if len(self.messages) == 2:
            raise OSError("second write failed")
        return [{"id": "msg-1"}]
