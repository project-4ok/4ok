from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

GraphqlTransport = Callable[[str, dict[str, object]], dict[str, object]]

DEFAULT_LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
DEFAULT_LINEAR_LIMIT = 1000
LINEAR_PAGE_SIZE = 100


@dataclass(frozen=True)
class LinearTapConfig:
    api_key: str
    endpoint: str = DEFAULT_LINEAR_GRAPHQL_URL
    limit: int = DEFAULT_LINEAR_LIMIT

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("LINEAR_API_KEY is required")
        if self.limit <= 0:
            raise ValueError("LINEAR_LIMIT must be positive")


def main() -> None:
    try:
        config = LinearTapConfig(
            api_key=os.environ.get("LINEAR_API_KEY", ""),
            endpoint=os.environ.get("LINEAR_GRAPHQL_URL", DEFAULT_LINEAR_GRAPHQL_URL),
            limit=int(os.environ.get("LINEAR_LIMIT", str(DEFAULT_LINEAR_LIMIT))),
        )
        for message in run_linear_tap(config):
            print(json.dumps(message, sort_keys=True))
    except Exception as exc:
        print(f"tap-gcb-linear failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def run_linear_tap(
    config: LinearTapConfig,
    *,
    graphql: GraphqlTransport | None = None,
) -> list[dict[str, Any]]:
    transport = graphql or graphql_transport(endpoint=config.endpoint, api_key=config.api_key)
    users: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    cursors: dict[str, str | None] = {"users": None, "issues": None, "comments": None}
    has_next = {"users": True, "issues": True, "comments": True}
    while any(has_next.values()) and max(len(users), len(issues), len(comments)) < config.limit:
        page_limit = min(
            LINEAR_PAGE_SIZE,
            config.limit - max(len(users), len(issues), len(comments)),
        )
        response = transport(
            _query(),
            {
                "first": page_limit,
                "usersAfter": cursors["users"],
                "issuesAfter": cursors["issues"],
                "commentsAfter": cursors["comments"],
            },
        )
        response_data = response.get("data")
        data: dict[str, object] = response_data if isinstance(response_data, dict) else {}
        users.extend(_user_record(node) for node in _nodes(data, "users")[:page_limit])
        issues.extend(_issue_record(node) for node in _nodes(data, "issues")[:page_limit])
        comments.extend(_comment_record(node) for node in _nodes(data, "comments")[:page_limit])
        for key in has_next:
            page_info = _page_info(data, key)
            has_next[key] = bool(page_info.get("hasNextPage"))
            if cursor := _string(page_info.get("endCursor")):
                cursors[key] = cursor

    messages: list[dict[str, Any]] = [_schema("linear_users")]
    messages.extend({"type": "RECORD", "stream": "linear_users", "record": row} for row in users)
    messages.append(_schema("linear_issues"))
    messages.extend({"type": "RECORD", "stream": "linear_issues", "record": row} for row in issues)
    messages.append(_schema("linear_comments"))
    messages.extend(
        {"type": "RECORD", "stream": "linear_comments", "record": row} for row in comments
    )
    messages.append({"type": "STATE", "value": {"bookmarks": _bookmarks(users, issues, comments)}})
    return messages


def graphql_transport(*, endpoint: str, api_key: str) -> GraphqlTransport:
    def _transport(query: str, variables: dict[str, object]) -> dict[str, object]:
        request = Request(
            endpoint,
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
                "User-Agent": "gcb-tap-linear/0.1",
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("Linear GraphQL response is not an object")
        if parsed.get("errors"):
            raise ValueError("Linear GraphQL response contains errors")
        return parsed

    return _transport


def _schema(stream: str) -> dict[str, Any]:
    return {"type": "SCHEMA", "stream": stream, "schema": {"type": "object"}}


def _query() -> str:
    return """
        query GcbLinearTap(
          $first: Int!,
          $usersAfter: String,
          $issuesAfter: String,
          $commentsAfter: String
        ) {
          users(first: $first, after: $usersAfter) {
            pageInfo { hasNextPage endCursor }
            nodes { id name email active createdAt updatedAt url }
          }
          issues(first: $first, after: $issuesAfter, orderBy: updatedAt) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id identifier title description url createdAt updatedAt
              creator { id }
              assignee { id }
              team { id key }
              state { name }
            }
          }
          comments(first: $first, after: $commentsAfter, orderBy: updatedAt) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id body url createdAt updatedAt
              user { id }
              issue { id identifier title team { id } }
            }
          }
        }
    """


def _user_record(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(node.get("id")),
        "display_name": _string(node.get("name")),
        "name": _string(node.get("name")),
        "email": _string(node.get("email")),
        "active": node.get("active"),
        "created_at": _string(node.get("createdAt") or node.get("created_at")),
        "updated_at": _string(node.get("updatedAt") or node.get("updated_at")),
        "url": _string(node.get("url")),
    }


def _issue_record(node: dict[str, Any]) -> dict[str, Any]:
    team = _dict(node.get("team"))
    return {
        "id": _string(node.get("id")),
        "identifier": _string(node.get("identifier")),
        "title": _string(node.get("title")),
        "description": _string(node.get("description")),
        "url": _string(node.get("url")),
        "created_at": _string(node.get("createdAt") or node.get("created_at")),
        "updated_at": _string(node.get("updatedAt") or node.get("updated_at")),
        "creator_id": _nested_id(node, "creator"),
        "assignee_id": _nested_id(node, "assignee"),
        "team_id": _string(team.get("id")),
        "team_key": _string(team.get("key")),
        "status": _string(_dict(node.get("state")).get("name")),
    }


def _comment_record(node: dict[str, Any]) -> dict[str, Any]:
    issue = _dict(node.get("issue"))
    team = _dict(issue.get("team"))
    return {
        "id": _string(node.get("id")),
        "body": _string(node.get("body")),
        "url": _string(node.get("url")),
        "created_at": _string(node.get("createdAt") or node.get("created_at")),
        "updated_at": _string(node.get("updatedAt") or node.get("updated_at")),
        "user_id": _nested_id(node, "user"),
        "issue_id": _string(issue.get("id")),
        "issue_identifier": _string(issue.get("identifier")),
        "issue_title": _string(issue.get("title")),
        "team_id": _string(team.get("id")),
    }


def _nodes(data: dict[str, object], key: str) -> list[dict[str, Any]]:
    connection = data.get(key)
    if not isinstance(connection, dict):
        return []
    nodes = connection.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def _page_info(data: dict[str, object], key: str) -> dict[str, Any]:
    connection = data.get(key)
    if not isinstance(connection, dict):
        return {}
    page_info = connection.get("pageInfo")
    return page_info if isinstance(page_info, dict) else {}


def _bookmarks(
    users: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    return {
        "linear_comments": {"updated_at": _max_updated_at(comments)},
        "linear_issues": {"updated_at": _max_updated_at(issues)},
        "linear_users": {"updated_at": _max_updated_at(users)},
    }


def _max_updated_at(records: list[dict[str, Any]]) -> str:
    return max((_string(record.get("updated_at")) for record in records), default="")


def _nested_id(node: dict[str, Any], key: str) -> str:
    return _string(_dict(node.get(key)).get("id"))


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
