import json
from pathlib import Path

from fourok.retrieval.graphiti_episodes import graphiti_episodes_from_source_snapshot

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures" / "honcho" / "linear_twenty_slack_sample.json"
)


def test_graphiti_episode_conversion_preserves_linear_issue_provenance() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"][0]["permission_refs"] = ["linear:team:ops", "workflow:renewals"]

    episodes = graphiti_episodes_from_source_snapshot(data, group_id="fourok-fixture")

    assert episodes[0] == {
        "uuid": "fourok:graphiti:linear:issue:ABC-123",
        "group_id": "fourok-fixture",
        "name": "linear:issue:ABC-123",
        "episode_body": (
            "source_ref: linear:issue:ABC-123\n"
            "source_url: https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting\n"
            "source_updated_at: 2026-06-01T10:15:00+00:00\n"
            "entities: employee:email:olivia@example.com\n"
            "permission_refs: linear:team:ops workflow:renewals\n"
            "\n"
            "Linear issue ABC-123: Olivia Smith created and assigned Olivia Smith a task titled "
            "'ask Robin to move meeting'. Description: Please ask Robin to move the meeting."
        ),
        "source": "message",
        "source_description": "linear message",
        "reference_time": "2026-06-01T10:15:00+00:00",
        "metadata": {
            "source": "linear",
            "source_ref": "linear:issue:ABC-123",
            "source_url": "https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
            "source_updated_at": "2026-06-01T10:15:00+00:00",
            "entities": ["employee:email:olivia@example.com"],
            "permission_refs": ["linear:team:ops", "workflow:renewals"],
            "routing_confidence": "high",
            "routing_rule": "linear_assignee_employee_match_v1",
        },
    }


def test_graphiti_episode_conversion_includes_catalog_json_episodes() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    episodes = graphiti_episodes_from_source_snapshot(data, group_id="fourok-fixture")

    catalog_episode = next(
        item for item in episodes if item["name"] == "twenty:workspaceMember:twenty-member-olivia"
    )
    assert catalog_episode == {
        "uuid": "fourok:graphiti:twenty:workspaceMember:twenty-member-olivia",
        "group_id": "fourok-fixture",
        "name": "twenty:workspaceMember:twenty-member-olivia",
        "episode_body": (
            "source_ref: twenty:workspaceMember:twenty-member-olivia\n"
            "source_url: \n"
            "source_updated_at: \n"
            "entities: employee:email:olivia@example.com\n"
            "permission_refs: \n"
            "\n"
            + json.dumps(
                {
                    "display_name": "Olivia Smith",
                    "email": "Olivia@example.com",
                    "entity_ref": "employee:email:olivia@example.com",
                    "source": "twenty",
                    "source_id": "twenty-member-olivia",
                    "source_type": "workspace_member",
                },
                sort_keys=True,
            )
        ),
        "source": "json",
        "source_description": "twenty workspace_member",
        "reference_time": None,
        "metadata": {
            "source": "twenty",
            "source_ref": "twenty:workspaceMember:twenty-member-olivia",
            "source_url": None,
            "source_updated_at": None,
            "entities": ["employee:email:olivia@example.com"],
        },
    }


def test_graphiti_episode_conversion_is_deterministically_ordered() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    episodes = graphiti_episodes_from_source_snapshot(data, group_id="fourok-fixture")

    assert [episode["name"] for episode in episodes] == [
        "linear:issue:ABC-123",
        "linear:project:project-meetings",
        "linear:team:ops",
        "linear:user:linear-user-olivia",
        "slack:user:U123456",
        "twenty:workspaceMember:twenty-member-olivia",
    ]
