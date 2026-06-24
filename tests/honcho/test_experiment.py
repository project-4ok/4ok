import json
from pathlib import Path

from gcb.honcho.experiment import build_honcho_sync_plan

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures" / "honcho" / "linear_twenty_slack_sample.json"
)


def test_build_honcho_sync_plan_routes_linear_issue_to_openclaw_slack_peer() -> None:
    plan = build_honcho_sync_plan(json.loads(FIXTURE.read_text(encoding="utf-8")))

    assert plan.summary == {
        "twenty_workspace_members": 1,
        "slack_users": 1,
        "linear_users": 1,
        "linear_issues": 1,
        "linear_comments": 0,
        "honcho_messages": 1,
        "unresolved_employee_mappings": 0,
        "unresolved_linear_users": 0,
        "unresolved_slack_users": 0,
    }
    assert plan.messages[0].peer == "slack_U123456"
    assert plan.messages[0].session == "slack_U123456:linear:2026-06"
    assert plan.messages[0].metadata["employee_peer"] == "employee:email:olivia@example.com"
    assert plan.messages[0].metadata["honcho_peer_id"] == "slack_U123456"
    assert plan.messages[0].metadata["source_ref"] == "linear:issue:ABC-123"
    assert plan.messages[0].metadata["candidate_entities"] == ["employee:email:olivia@example.com"]
    assert plan.source_names == ["linear", "slack", "twenty"]
    assert plan.source_imports == {
        "linear:project:project-meetings": {
            "source": "linear",
            "source_type": "project",
            "source_id": "project-meetings",
            "name": "Meeting Operations",
        },
        "linear:team:ops": {
            "source": "linear",
            "source_type": "team",
            "source_id": "ops",
            "key": "OPS",
            "name": "Operations",
        },
        "linear:user:linear-user-olivia": {
            "source": "linear",
            "source_type": "user",
            "source_id": "linear-user-olivia",
            "display_name": "Olivia Smith",
            "email": "olivia@example.com",
            "entity_ref": "employee:email:olivia@example.com",
        },
        "slack:user:U123456": {
            "source": "slack",
            "source_type": "user",
            "source_id": "U123456",
            "display_name": "Olivia Smith",
            "email": "olivia@example.com",
            "entity_ref": "employee:email:olivia@example.com",
            "honcho_peer_id": "slack_U123456",
            "deleted": "false",
            "is_bot": "false",
        },
        "twenty:workspaceMember:twenty-member-olivia": {
            "source": "twenty",
            "source_type": "workspace_member",
            "source_id": "twenty-member-olivia",
            "display_name": "Olivia Smith",
            "email": "Olivia@example.com",
            "entity_ref": "employee:email:olivia@example.com",
        },
    }


def test_build_honcho_sync_plan_preserves_source_permission_refs() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"][0]["permission_refs"] = ["linear:team:ops", "workflow:renewals"]

    plan = build_honcho_sync_plan(data)

    assert plan.messages[0].metadata["permission_refs"] == [
        "linear:team:ops",
        "workflow:renewals",
    ]


def test_build_honcho_sync_plan_routes_linear_comment_to_commenter_peer() -> None:
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

    assert plan.summary["linear_comments"] == 1
    assert plan.summary["honcho_messages"] == 2
    comment_message = plan.messages[1]
    assert comment_message.peer == "slack_U123456"
    assert comment_message.session == "slack_U123456:linear:2026-06"
    assert comment_message.text == (
        "Linear comment on ABC-123: Olivia Smith commented on 'ask Robin to move meeting': "
        "Robin can move the meeting to Thursday."
    )
    assert comment_message.metadata == {
        "source": "linear",
        "source_ref": "linear:comment:linear-comment-1",
        "source_url": "https://linear.app/acme/issue/ABC-123#comment-1",
        "source_updated_at": "2026-06-01T10:35:00+00:00",
        "actors": ["employee:email:olivia@example.com"],
        "assignees": [],
        "employee_peer": "employee:email:olivia@example.com",
        "honcho_peer_id": "slack_U123456",
        "candidate_entities": ["employee:email:olivia@example.com"],
        "aggregate_fallback_peer": "linear:team:ops",
        "routing_confidence": "high",
        "routing_rule": "linear_commenter_employee_match_v1",
        "related_issue_ref": "linear:issue:ABC-123",
    }


def test_build_honcho_sync_plan_uses_aggregate_fallback_without_slack_mapping() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["slack_users"] = []

    plan = build_honcho_sync_plan(data)

    assert plan.summary["unresolved_employee_mappings"] == 1
    assert plan.messages[0].peer == "linear:team:ops"
    assert plan.messages[0].metadata["employee_peer"] == "employee:email:olivia@example.com"
    assert plan.messages[0].metadata["honcho_peer_id"] is None
    assert plan.messages[0].metadata["routing_confidence"] == "fallback"


def test_build_honcho_sync_plan_routes_to_creator_when_issue_has_no_assignee() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"][0]["assignee_id"] = None

    plan = build_honcho_sync_plan(data)

    assert plan.messages[0].peer == "slack_U123456"
    assert plan.messages[0].metadata["actors"] == ["employee:email:olivia@example.com"]
    assert plan.messages[0].metadata["assignees"] == []
    assert plan.messages[0].metadata["routing_rule"] == "linear_creator_employee_match_v1"


def test_build_honcho_sync_plan_routes_to_aggregate_when_no_employee_matches() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_users"] = [
        {
            "id": "linear-user-external",
            "display_name": "External User",
            "email": "external@example.com",
        }
    ]
    data["linear_issues"][0]["creator_id"] = "linear-user-external"
    data["linear_issues"][0]["assignee_id"] = None

    plan = build_honcho_sync_plan(data)

    assert plan.summary["unresolved_linear_users"] == 1
    assert plan.messages[0].peer == "linear:team:ops"
    assert plan.messages[0].metadata["employee_peer"] is None
    assert plan.messages[0].metadata["honcho_peer_id"] is None
    assert plan.messages[0].metadata["routing_rule"] == "linear_aggregate_fallback_v1"


def test_build_honcho_sync_plan_reports_unmatched_live_identity_catalogs() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["twenty_workspace_members"] = []

    plan = build_honcho_sync_plan(data)

    assert plan.summary["unresolved_linear_users"] == 1
    assert plan.summary["unresolved_slack_users"] == 1
    assert plan.messages[0].peer == "linear:team:ops"
