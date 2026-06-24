from io import BytesIO
from urllib.error import HTTPError

import pytest

from fourok.honcho.sources import (
    LinearClient,
    SlackClient,
    SourceClientError,
    TwentyClient,
    collect_source_snapshot,
    graphql_transport,
    rest_transport,
    slack_transport,
)


def test_twenty_client_normalizes_workspace_members() -> None:
    calls: list[dict[str, object]] = []

    def fake_rest(path: str, params: dict[str, object]) -> dict[str, object]:
        calls.append({"path": path, "params": params})
        return {
            "data": {
                "workspaceMembers": [
                    {
                        "id": "twenty-member-olivia",
                        "name": {"firstName": "Olivia", "lastName": "Smith"},
                        "userEmail": "Olivia@example.com",
                    }
                ]
            }
        }

    records = TwentyClient(rest=fake_rest).workspace_members(limit=1)

    assert records == [
        {
            "id": "twenty-member-olivia",
            "display_name": "Olivia Smith",
            "email": "Olivia@example.com",
        }
    ]
    assert calls == [{"path": "workspaceMembers", "params": {"limit": 1}}]


def test_slack_client_normalizes_users_for_identity_only() -> None:
    def fake_api(method: str, params: dict[str, object]) -> dict[str, object]:
        assert method == "users.list"
        assert params == {"limit": 2}
        return {
            "ok": True,
            "members": [
                {
                    "id": "U123456",
                    "name": "olivia",
                    "deleted": False,
                    "is_bot": False,
                    "profile": {
                        "real_name": "Olivia Smith",
                        "email": "olivia@example.com",
                    },
                }
            ],
        }

    records = SlackClient(api=fake_api).users(limit=2)

    assert records == [
        {
            "id": "U123456",
            "display_name": "Olivia Smith",
            "email": "olivia@example.com",
            "deleted": False,
            "is_bot": False,
        }
    ]


def test_slack_client_raises_clean_error_on_api_failure() -> None:
    def fake_api(method: str, params: dict[str, object]) -> dict[str, object]:
        return {"ok": False, "error": "invalid_auth"}

    with pytest.raises(SourceClientError, match="Slack users.list failed: invalid_auth"):
        SlackClient(api=fake_api).users(limit=2)


def test_linear_client_normalizes_catalogs_and_issues() -> None:
    queries: list[dict[str, object]] = []

    def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
        queries.append({"query": query, "variables": variables})
        return {
            "data": {
                "users": {
                    "nodes": [
                        {
                            "id": "linear-user-olivia",
                            "name": "Olivia Smith",
                            "email": "olivia@example.com",
                        }
                    ]
                },
                "teams": {
                    "nodes": [
                        {
                            "id": "ops",
                            "key": "OPS",
                            "name": "Operations",
                        }
                    ]
                },
                "projects": {
                    "nodes": [
                        {
                            "id": "project-meetings",
                            "name": "Meeting Operations",
                        }
                    ]
                },
                "issues": {
                    "nodes": [
                        {
                            "id": "linear-issue-abc-123",
                            "identifier": "ABC-123",
                            "title": "ask Robin to move meeting",
                            "description": "Please ask Robin to move the meeting.",
                            "url": "https://linear.app/acme/issue/ABC-123",
                            "createdAt": "2026-06-01T10:00:00+00:00",
                            "updatedAt": "2026-06-01T10:15:00+00:00",
                            "creator": {"id": "linear-user-olivia"},
                            "assignee": {"id": "linear-user-olivia"},
                            "team": {"id": "ops"},
                            "project": {"id": "project-meetings"},
                        }
                    ]
                },
                "comments": {
                    "nodes": [
                        {
                            "id": "linear-comment-1",
                            "body": "Robin can move the meeting to Thursday.",
                            "url": "https://linear.app/acme/issue/ABC-123#comment-1",
                            "createdAt": "2026-06-01T10:30:00+00:00",
                            "updatedAt": "2026-06-01T10:35:00+00:00",
                            "user": {"id": "linear-user-olivia"},
                            "issue": {
                                "id": "linear-issue-abc-123",
                                "identifier": "ABC-123",
                                "title": "ask Robin to move meeting",
                                "url": "https://linear.app/acme/issue/ABC-123",
                                "team": {"id": "ops"},
                            },
                        }
                    ]
                },
            }
        }

    snapshot = LinearClient(graphql=fake_graphql).bounded_snapshot(
        event_limit=3,
        catalog_limit=25,
    )

    assert snapshot["linear_users"] == [
        {
            "id": "linear-user-olivia",
            "display_name": "Olivia Smith",
            "email": "olivia@example.com",
        }
    ]
    assert snapshot["linear_teams"] == [{"id": "ops", "key": "OPS", "name": "Operations"}]
    assert snapshot["linear_projects"] == [{"id": "project-meetings", "name": "Meeting Operations"}]
    assert snapshot["linear_issues"][0] == {
        "id": "linear-issue-abc-123",
        "identifier": "ABC-123",
        "title": "ask Robin to move meeting",
        "description": "Please ask Robin to move the meeting.",
        "url": "https://linear.app/acme/issue/ABC-123",
        "team_id": "ops",
        "project_id": "project-meetings",
        "created_at": "2026-06-01T10:00:00+00:00",
        "updated_at": "2026-06-01T10:15:00+00:00",
        "creator_id": "linear-user-olivia",
        "assignee_id": "linear-user-olivia",
    }
    assert snapshot["linear_comments"][0] == {
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
    assert queries[0]["variables"] == {"eventFirst": 3, "catalogFirst": 25}


def test_linear_client_filters_issues_by_updated_since_when_provided() -> None:
    queries: list[dict[str, object]] = []

    def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
        queries.append({"query": query, "variables": variables})
        return {
            "data": {
                "users": {"nodes": []},
                "teams": {"nodes": []},
                "projects": {"nodes": []},
                "issues": {"nodes": []},
                "comments": {"nodes": []},
            }
        }

    snapshot = LinearClient(graphql=fake_graphql).bounded_snapshot(
        event_limit=3,
        catalog_limit=25,
        updated_since="2026-06-01T10:05:00+00:00",
    )

    assert snapshot["linear_issues"] == []
    assert queries[0]["variables"] == {
        "eventFirst": 3,
        "catalogFirst": 25,
        "updatedAfter": "2026-06-01T10:05:00+00:00",
    }
    assert "$updatedAfter: DateTimeOrDuration!" in str(queries[0]["query"])
    assert "updatedAt: { gte: $updatedAfter }" in str(queries[0]["query"])


def test_collect_source_snapshot_combines_live_source_records() -> None:
    def fake_rest_transport(*, base_url: str, api_key: str):
        def fake_rest(path: str, params: dict[str, object]) -> dict[str, object]:
            assert base_url == "https://twenty.example/rest"
            assert path == "workspaceMembers"
            assert params == {"limit": 50}
            return {
                "data": {
                    "workspaceMembers": [
                        {
                            "id": "twenty-member-olivia",
                            "name": {"firstName": "Olivia", "lastName": "Smith"},
                            "userEmail": "olivia@example.com",
                        }
                    ]
                }
            }

        return fake_rest

    def fake_graphql_transport(*, endpoint: str, api_key: str, **kwargs):
        def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
            if endpoint == "https://api.linear.app/graphql":
                return {
                    "data": {
                        "users": {
                            "nodes": [
                                {
                                    "id": "linear-user-olivia",
                                    "name": "Olivia Smith",
                                    "email": "olivia@example.com",
                                }
                            ]
                        },
                        "teams": {"nodes": [{"id": "ops", "key": "OPS", "name": "Operations"}]},
                        "projects": {
                            "nodes": [{"id": "project-meetings", "name": "Meeting Operations"}]
                        },
                        "issues": {"nodes": []},
                        "comments": {"nodes": []},
                    }
                }
            raise AssertionError(f"unexpected GraphQL endpoint: {endpoint}")

        return fake_graphql

    def fake_slack_transport(*, api_key: str):
        def fake_api(method: str, params: dict[str, object]) -> dict[str, object]:
            return {
                "ok": True,
                "members": [
                    {
                        "id": "U123456",
                        "profile": {"real_name": "Olivia Smith", "email": "olivia@example.com"},
                    }
                ],
            }

        return fake_api

    snapshot = collect_source_snapshot(
        {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
            "TWENTY_REST_URL": "https://twenty.example/rest",
        },
        limit=2,
        catalog_limit=50,
        graphql_transport_factory=fake_graphql_transport,
        rest_transport_factory=fake_rest_transport,
        slack_transport_factory=fake_slack_transport,
    )

    assert snapshot["twenty_workspace_members"][0]["id"] == "twenty-member-olivia"
    assert snapshot["slack_users"][0]["id"] == "U123456"
    assert snapshot["linear_users"][0]["id"] == "linear-user-olivia"
    assert snapshot["linear_teams"][0]["id"] == "ops"
    assert snapshot["linear_projects"][0]["id"] == "project-meetings"
    assert snapshot["linear_issues"] == []
    assert snapshot["linear_comments"] == []


def test_collect_source_snapshot_applies_linear_checkpoint_overlap() -> None:
    captured_variables: list[dict[str, object]] = []

    def fake_graphql_transport(*, endpoint: str, api_key: str, **kwargs):
        def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
            captured_variables.append(variables)
            return {
                "data": {
                    "users": {"nodes": []},
                    "teams": {"nodes": []},
                    "projects": {"nodes": []},
                    "issues": {"nodes": []},
                    "comments": {"nodes": []},
                }
            }

        return fake_graphql

    collect_source_snapshot(
        {"LINEAR_API_KEY": "linear-secret"},
        limit=2,
        catalog_limit=50,
        sources={"linear"},
        checkpoints={"linear": "2026-06-01T10:15:00+00:00"},
        overlap_minutes=10,
        graphql_transport_factory=fake_graphql_transport,
    )

    assert captured_variables == [
        {
            "eventFirst": 2,
            "catalogFirst": 50,
            "updatedAfter": "2026-06-01T10:05:00+00:00",
        }
    ]


def test_collect_source_snapshot_can_skip_unselected_sources() -> None:
    called_endpoints: list[str] = []

    def fake_graphql_transport(*, endpoint: str, api_key: str, **kwargs):
        called_endpoints.append(endpoint)

        def fake_graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
            assert endpoint == "https://api.linear.app/graphql"
            return {
                "data": {
                    "users": {
                        "nodes": [
                            {
                                "id": "linear-user-olivia",
                                "name": "Olivia Smith",
                                "email": "olivia@example.com",
                            }
                        ]
                    },
                    "teams": {"nodes": []},
                    "projects": {"nodes": []},
                    "issues": {"nodes": []},
                    "comments": {"nodes": []},
                }
            }

        return fake_graphql

    def fake_slack_transport(*, api_key: str):
        def fake_api(method: str, params: dict[str, object]) -> dict[str, object]:
            return {
                "ok": True,
                "members": [
                    {
                        "id": "U123456",
                        "profile": {"real_name": "Olivia Smith", "email": "olivia@example.com"},
                    }
                ],
            }

        return fake_api

    snapshot = collect_source_snapshot(
        {
            "LINEAR_API_KEY": "linear-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        },
        limit=2,
        sources={"linear", "slack"},
        graphql_transport_factory=fake_graphql_transport,
        slack_transport_factory=fake_slack_transport,
    )

    assert called_endpoints == ["https://api.linear.app/graphql"]
    assert snapshot["linear_users"][0]["id"] == "linear-user-olivia"
    assert snapshot["slack_users"][0]["id"] == "U123456"
    assert snapshot["twenty_workspace_members"] == []


def test_graphql_transport_can_send_raw_authorization_header(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout: int):
        captured["authorization"] = dict(request.header_items())["Authorization"]
        return _Response({"data": {"ok": True}})

    monkeypatch.setattr("fourok.honcho.sources.urlopen", fake_urlopen)
    transport = graphql_transport(
        endpoint="https://api.linear.app/graphql",
        api_key="linear-secret",
        bearer=False,
    )

    assert transport("query { ok }", {}) == {"data": {"ok": True}}
    assert captured["authorization"] == "linear-secret"


def test_graphql_transport_raises_clean_source_error_on_http_failure(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=BytesIO(b"error code: 1010"),
        )

    monkeypatch.setattr("fourok.honcho.sources.urlopen", fake_urlopen)
    transport = graphql_transport(endpoint="https://api.twenty.com/graphql", api_key="secret")

    with pytest.raises(SourceClientError, match="Source request failed with HTTP 403"):
        transport("query { ok }", {})


def test_graphql_transport_raises_clean_source_error_on_graphql_errors(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        return _Response(
            {
                "errors": [
                    {
                        "message": "Variable has invalid value",
                        "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"},
                    }
                ]
            }
        )

    monkeypatch.setattr("fourok.honcho.sources.urlopen", fake_urlopen)
    transport = graphql_transport(endpoint="https://api.linear.app/graphql", api_key="secret")

    with pytest.raises(SourceClientError, match="GraphQL request returned errors"):
        transport("query { ok }", {})


def test_rest_transport_uses_bearer_auth_and_query_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return _Response({"data": {"workspaceMembers": []}})

    monkeypatch.setattr("fourok.honcho.sources.urlopen", fake_urlopen)
    transport = rest_transport(base_url="https://api.twenty.com/rest/", api_key="secret")

    assert transport("workspaceMembers", {"limit": 2}) == {"data": {"workspaceMembers": []}}
    assert captured["url"] == "https://api.twenty.com/rest/workspaceMembers?limit=2"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["User-agent"] == "fourok-honcho-source/0.1"


def test_slack_transport_retries_once_on_rate_limit(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_urlopen(request, timeout: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                url=request.full_url,
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "0"},
                fp=BytesIO(b'{"ok":false,"error":"ratelimited"}'),
            )
        return _Response({"ok": True, "members": []})

    monkeypatch.setattr("fourok.honcho.sources.urlopen", fake_urlopen)
    monkeypatch.setattr("fourok.honcho.sources.sleep", sleeps.append)
    transport = slack_transport(api_key="secret")

    assert transport("users.list", {"limit": 2}) == {"ok": True, "members": []}
    assert calls == 2
    assert sleeps == [0.0]


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")
