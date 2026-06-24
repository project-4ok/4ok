from pathlib import Path

import pytest

from fourok.etl.extract.connectors import (
    land_singer_records,
    linear_issue_source_record_from_raw,
    load_landed_source_records,
    load_linear_source_records,
)
from fourok.etl.extract.linear_tap import LinearTapConfig, run_linear_tap

FIXTURES = Path(__file__).parents[3] / "fixtures" / "connectors"
SINGER_LINEAR_WORK_ITEMS = FIXTURES / "singer_linear_work_items.jsonl"


def test_linear_singer_records_map_to_source_records() -> None:
    source_records = load_linear_source_records(SINGER_LINEAR_WORK_ITEMS)

    assert [record.source_ref for record in source_records] == [
        "linear:user:linear-user-olivia",
        "linear:issue:OPS-123",
        "linear:comment:comment-1",
    ]
    assert [record.record_type for record in source_records] == [
        "person",
        "work_item",
        "message",
    ]
    assert source_records[0].identity_refs == ("linear:email:olivia@example.com",)
    assert source_records[1].title == "Prepare Alpha cancellation summary"
    assert source_records[1].body == (
        "OPS-123 Prepare Alpha cancellation summary "
        "Prepare the contract status summary for Alpha Hausverwaltung."
    )
    assert source_records[1].author_ref == "linear-user-olivia"
    assert source_records[1].thread_ref == "linear:issue:OPS-123"
    assert source_records[1].permission_refs == ("linear:team:team-ops",)
    assert source_records[1].identity_refs == (
        "linear-user-olivia",
        "linear-user-olivia",
    )
    assert source_records[1].metadata == {
        "assignee_id": "linear-user-olivia",
        "creator_id": "linear-user-olivia",
        "source_object_type": "issue",
        "status": "In Progress",
        "team_id": "team-ops",
        "team_key": "OPS",
    }
    assert source_records[2].thread_ref == "linear:issue:OPS-123"
    assert source_records[2].author_ref == "linear-user-olivia"


def test_linear_raw_landing_can_be_reloaded_into_source_records() -> None:
    landing_dir = Path(".local/test-artifacts/connectors/linear-raw-landing")
    if landing_dir.exists():
        for path in landing_dir.glob("*"):
            path.unlink()

    report = land_singer_records(SINGER_LINEAR_WORK_ITEMS, landing_dir)
    users = load_landed_source_records(landing_dir, stream="linear_users")
    issues = load_landed_source_records(landing_dir, stream="linear_issues")
    comments = load_landed_source_records(landing_dir, stream="linear_comments")

    assert report.record_count == 3
    assert report.streams == {
        "linear_comments": 1,
        "linear_issues": 1,
        "linear_users": 1,
    }
    assert report.schema_messages == 3
    assert report.state_messages == 1
    assert users[0].source_ref == "linear:user:linear-user-olivia"
    assert issues[0].source_ref == "linear:issue:OPS-123"
    assert comments[0].source_ref == "linear:comment:comment-1"


def test_linear_issue_adapter_rejects_missing_identifier_before_source_records() -> None:
    with pytest.raises(ValueError, match="Linear issue record requires identifier"):
        linear_issue_source_record_from_raw({"title": "Missing identifier"})


def test_committed_meltano_config_wires_linear_fixture_job() -> None:
    config = (Path(__file__).parents[3] / "meltano.yml").read_text(encoding="utf-8")

    assert "tap-fourok-linear-fixture" in config
    assert "fixtures/connectors/singer_linear_work_items.jsonl" in config
    assert "singer-linear-fixture-to-raw" in config
    assert "tap-fourok-linear-fixture target-fourok-raw-jsonl" in config


def test_linear_tap_emits_users_issues_comments_and_state() -> None:
    calls: list[dict[str, object]] = []

    def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append({"query": query, "variables": variables})
        return {
            "data": {
                "users": {
                    "nodes": [
                        {
                            "id": "linear-user-olivia",
                            "name": "Olivia Example",
                            "email": "olivia@example.com",
                            "active": True,
                            "createdAt": "2026-06-01T08:00:00Z",
                            "updatedAt": "2026-06-01T08:05:00Z",
                            "url": "https://linear.app/fourok/profiles/olivia",
                        }
                    ]
                },
                "issues": {
                    "nodes": [
                        {
                            "id": "linear-issue-1",
                            "identifier": "OPS-123",
                            "title": "Prepare Alpha cancellation summary",
                            "description": "Prepare the contract status summary.",
                            "url": "https://linear.app/fourok/issue/OPS-123",
                            "createdAt": "2026-06-02T10:00:00Z",
                            "updatedAt": "2026-06-02T11:00:00Z",
                            "creator": {"id": "linear-user-olivia"},
                            "assignee": {"id": "linear-user-olivia"},
                            "team": {"id": "team-ops", "key": "OPS"},
                            "state": {"name": "In Progress"},
                        }
                    ]
                },
                "comments": {
                    "nodes": [
                        {
                            "id": "comment-1",
                            "body": "Finance needs latest evidence.",
                            "url": "https://linear.app/fourok/issue/OPS-123#comment-1",
                            "createdAt": "2026-06-02T11:15:00Z",
                            "updatedAt": "2026-06-02T11:16:00Z",
                            "user": {"id": "linear-user-olivia"},
                            "issue": {
                                "identifier": "OPS-123",
                                "title": "Prepare Alpha cancellation summary",
                                "team": {"id": "team-ops"},
                            },
                        }
                    ]
                },
            }
        }

    messages = run_linear_tap(
        LinearTapConfig(api_key="secret", endpoint="https://linear.example/graphql", limit=5),
        graphql=fake_graphql,
    )

    assert [message["type"] for message in messages] == [
        "SCHEMA",
        "RECORD",
        "SCHEMA",
        "RECORD",
        "SCHEMA",
        "RECORD",
        "STATE",
    ]
    assert [message.get("stream") for message in messages if message["type"] == "RECORD"] == [
        "linear_users",
        "linear_issues",
        "linear_comments",
    ]
    assert messages[-1]["value"] == {
        "bookmarks": {
            "linear_comments": {"updated_at": "2026-06-02T11:16:00Z"},
            "linear_issues": {"updated_at": "2026-06-02T11:00:00Z"},
            "linear_users": {"updated_at": "2026-06-01T08:05:00Z"},
        }
    }
    assert calls[0]["variables"] == {
        "first": 5,
        "usersAfter": None,
        "issuesAfter": None,
        "commentsAfter": None,
    }


def test_linear_tap_paginates_each_connection_until_configured_limit() -> None:
    calls: list[dict[str, object]] = []

    def connection(kind: str, start: int, count: int, *, has_next: bool) -> dict[str, object]:
        nodes = [
            {
                "id": f"{kind}-{index}",
                "name": f"{kind.title()} {index}",
                "email": f"{kind}-{index}@example.com",
                "identifier": f"OPS-{index}",
                "title": f"{kind.title()} {index}",
                "body": f"{kind.title()} body {index}",
                "updatedAt": f"2026-06-09T00:{index:02d}:00Z",
            }
            for index in range(start, start + count)
        ]
        return {
            "nodes": nodes,
            "pageInfo": {
                "hasNextPage": has_next,
                "endCursor": f"cursor-{kind}-{start + count - 1}",
            },
        }

    def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append({"query": query, "variables": dict(variables)})
        first = variables["first"]
        assert isinstance(first, int)
        assert first <= 100
        page = 0 if variables["usersAfter"] is None else 100
        page_size = 100 if page == 0 else 50
        return {
            "data": {
                "users": connection("user", page, page_size, has_next=page == 0),
                "issues": connection("issue", page, page_size, has_next=page == 0),
                "comments": connection("comment", page, page_size, has_next=page == 0),
            }
        }

    messages = run_linear_tap(
        LinearTapConfig(api_key="secret", endpoint="https://linear.example/graphql", limit=150),
        graphql=fake_graphql,
    )

    assert sum(1 for message in messages if message.get("stream") == "linear_users") == 151
    assert sum(1 for message in messages if message.get("stream") == "linear_issues") == 151
    assert sum(1 for message in messages if message.get("stream") == "linear_comments") == 151
    assert [call["variables"] for call in calls] == [
        {
            "first": 100,
            "usersAfter": None,
            "issuesAfter": None,
            "commentsAfter": None,
        },
        {
            "first": 50,
            "usersAfter": "cursor-user-99",
            "issuesAfter": "cursor-issue-99",
            "commentsAfter": "cursor-comment-99",
        },
    ]


def test_linear_tap_output_feeds_existing_source_record_adapter(tmp_path: Path) -> None:
    def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
        return {
            "data": {
                "users": {
                    "nodes": [
                        {
                            "id": "linear-user-olivia",
                            "name": "Olivia Example",
                            "email": "olivia@example.com",
                        }
                    ]
                },
                "issues": {
                    "nodes": [
                        {
                            "identifier": "OPS-123",
                            "title": "Prepare Alpha cancellation summary",
                            "team": {"id": "team-ops"},
                        }
                    ]
                },
                "comments": {
                    "nodes": [
                        {
                            "id": "comment-1",
                            "body": "Finance needs latest evidence.",
                            "issue": {"identifier": "OPS-123"},
                        }
                    ]
                },
            }
        }

    messages = run_linear_tap(
        LinearTapConfig(api_key="secret", endpoint="https://linear.example/graphql", limit=5),
        graphql=fake_graphql,
    )
    singer_file = tmp_path / "linear.singer.jsonl"
    singer_file.write_text(
        "\n".join(__import__("json").dumps(message, sort_keys=True) for message in messages) + "\n",
        encoding="utf-8",
    )

    records = load_linear_source_records(singer_file)

    assert [record.source_ref for record in records] == [
        "linear:user:linear-user-olivia",
        "linear:issue:OPS-123",
        "linear:comment:comment-1",
    ]


def test_linear_tap_requires_api_key() -> None:
    with pytest.raises(ValueError, match="LINEAR_API_KEY is required"):
        LinearTapConfig(api_key="", endpoint="https://linear.example/graphql")
