from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GraphqlTransport = Callable[[str, dict[str, object]], dict[str, object]]
RestTransport = Callable[[str, dict[str, object]], dict[str, object]]
SlackTransport = Callable[[str, dict[str, object]], dict[str, object]]
GraphqlTransportFactory = Callable[..., GraphqlTransport]
RestTransportFactory = Callable[..., RestTransport]
SlackTransportFactory = Callable[..., SlackTransport]

DEFAULT_LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
DEFAULT_TWENTY_REST_URL = "https://api.twenty.com/rest"
SOURCE_NAMES = frozenset({"linear", "twenty", "slack"})


class SourceClientError(RuntimeError):
    pass


def collect_source_snapshot(
    secrets: dict[str, str],
    *,
    limit: int,
    catalog_limit: int = 100,
    sources: set[str] | None = None,
    checkpoints: dict[str, str] | None = None,
    overlap_minutes: int = 5,
    graphql_transport_factory: GraphqlTransportFactory | None = None,
    rest_transport_factory: RestTransportFactory | None = None,
    slack_transport_factory: SlackTransportFactory | None = None,
) -> dict[str, list[dict[str, object]]]:
    selected_sources = _validated_sources(sources)
    graphql_factory = graphql_transport_factory or graphql_transport
    rest_factory = rest_transport_factory or rest_transport
    slack_factory = slack_transport_factory or slack_transport
    snapshot: dict[str, list[dict[str, object]]] = {
        "linear_users": [],
        "linear_teams": [],
        "linear_projects": [],
        "linear_issues": [],
        "linear_comments": [],
        "twenty_workspace_members": [],
        "slack_users": [],
    }
    if "linear" in selected_sources:
        linear = LinearClient(
            graphql=graphql_factory(
                endpoint=secrets.get("LINEAR_GRAPHQL_URL", DEFAULT_LINEAR_GRAPHQL_URL),
                api_key=secrets["LINEAR_API_KEY"],
                bearer=False,
            )
        )
        snapshot.update(
            linear.bounded_snapshot(
                event_limit=limit,
                catalog_limit=catalog_limit,
                updated_since=_checkpoint_with_overlap(
                    checkpoints,
                    connector_name="linear",
                    overlap_minutes=overlap_minutes,
                ),
            )
        )
    if "twenty" in selected_sources:
        twenty = TwentyClient(
            rest=rest_factory(
                base_url=secrets.get("TWENTY_REST_URL", DEFAULT_TWENTY_REST_URL),
                api_key=secrets["TWENTY_API_KEY"],
            )
        )
        snapshot["twenty_workspace_members"] = twenty.workspace_members(limit=catalog_limit)
    if "slack" in selected_sources:
        slack = SlackClient(api=slack_factory(api_key=secrets["SLACK_BOT_TOKEN"]))
        snapshot["slack_users"] = slack.users(limit=catalog_limit)
    return snapshot


def _validated_sources(sources: set[str] | None) -> set[str]:
    if sources is None:
        return set(SOURCE_NAMES)
    unknown = sorted(sources - SOURCE_NAMES)
    if unknown:
        raise SourceClientError(f"unknown Honcho source selection: {', '.join(unknown)}")
    return set(sources)


def _checkpoint_with_overlap(
    checkpoints: dict[str, str] | None,
    *,
    connector_name: str,
    overlap_minutes: int,
) -> str | None:
    if not checkpoints:
        return None
    checkpoint = checkpoints.get(connector_name)
    if checkpoint is None:
        return None
    try:
        parsed = datetime.fromisoformat(checkpoint.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceClientError(f"invalid {connector_name} checkpoint timestamp") from exc
    return (parsed - timedelta(minutes=overlap_minutes)).isoformat()


class TwentyClient:
    def __init__(self, *, rest: RestTransport) -> None:
        self.rest = rest

    def workspace_members(self, *, limit: int) -> list[dict[str, object]]:
        response = self.rest("workspaceMembers", {"limit": limit})
        return [
            {
                "id": str(node.get("id")),
                "display_name": _display_name_from_twenty_name(node.get("name")),
                "email": node.get("userEmail"),
            }
            for node in _rest_records(response, "workspaceMembers")
            if node.get("id")
        ]


class SlackClient:
    def __init__(self, *, api: SlackTransport) -> None:
        self.api = api

    def users(self, *, limit: int) -> list[dict[str, object]]:
        response = self.api("users.list", {"limit": limit})
        if response.get("ok") is False:
            raise SourceClientError(
                f"Slack users.list failed: {response.get('error') or 'unknown'}"
            )
        members = response.get("members")
        if not isinstance(members, list):
            return []
        return [_slack_user(member) for member in members if isinstance(member, dict)]


class LinearClient:
    def __init__(self, *, graphql: GraphqlTransport) -> None:
        self.graphql = graphql

    def bounded_snapshot(
        self,
        *,
        event_limit: int,
        catalog_limit: int,
        updated_since: str | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        response = self.graphql(
            _linear_snapshot_query(updated_since=updated_since),
            _linear_snapshot_variables(
                event_limit=event_limit,
                catalog_limit=catalog_limit,
                updated_since=updated_since,
            ),
        )
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        return {
            "linear_users": [_linear_user(node) for node in _nodes(data, "users")],
            "linear_teams": [_linear_team(node) for node in _nodes(data, "teams")],
            "linear_projects": [_linear_project(node) for node in _nodes(data, "projects")],
            "linear_issues": [_linear_issue(node) for node in _nodes(data, "issues")],
            "linear_comments": [_linear_comment(node) for node in _nodes(data, "comments")],
        }


def graphql_transport(*, endpoint: str, api_key: str, bearer: bool = True) -> GraphqlTransport:
    def _transport(query: str, variables: dict[str, object]) -> dict[str, object]:
        request = Request(
            endpoint,
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}" if bearer else api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return _send_json_request(request)

    return _transport


def rest_transport(*, base_url: str, api_key: str) -> RestTransport:
    normalized_base_url = base_url.rstrip("/")

    def _transport(path: str, params: dict[str, object]) -> dict[str, object]:
        encoded_params = urlencode(
            {
                key: value
                for key, value in params.items()
                if isinstance(key, str) and value is not None
            }
        )
        url = f"{normalized_base_url}/{path.lstrip('/')}"
        if encoded_params:
            url = f"{url}?{encoded_params}"
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "fourok-honcho-source/0.1",
            },
            method="GET",
        )
        return _send_json_request(request)

    return _transport


def slack_transport(*, api_key: str) -> SlackTransport:
    def _transport(method: str, params: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"https://slack.com/api/{method}",
            data=json.dumps(params).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return _send_json_request(request, retry_rate_limit=True)

    return _transport


def _linear_snapshot_query(*, updated_since: str | None) -> str:
    issues_arguments = (
        "first: $eventFirst, orderBy: updatedAt, filter: { updatedAt: { gte: $updatedAfter }}"
        if updated_since is not None
        else "first: $eventFirst, orderBy: updatedAt"
    )
    updated_after_variable = (
        ", $updatedAfter: DateTimeOrDuration!" if updated_since is not None else ""
    )
    return f"""
            query HonchoLinearSnapshot(
              $eventFirst: Int!,
              $catalogFirst: Int!{updated_after_variable}
            ) {{
              users(first: $catalogFirst) {{ nodes {{ id name email }} }}
              teams(first: $catalogFirst) {{ nodes {{ id key name }} }}
              projects(first: $catalogFirst) {{ nodes {{ id name }} }}
              issues({issues_arguments}) {{
                nodes {{
                  id identifier title description url createdAt updatedAt
                  creator {{ id }}
                  assignee {{ id }}
                  team {{ id }}
                  project {{ id }}
                }}
              }}
              comments({issues_arguments}) {{
                nodes {{
                  id body url createdAt updatedAt
                  user {{ id }}
                  issue {{
                    id identifier title url
                    team {{ id }}
                  }}
                }}
              }}
            }}
            """


def _linear_snapshot_variables(
    *,
    event_limit: int,
    catalog_limit: int,
    updated_since: str | None,
) -> dict[str, object]:
    variables: dict[str, object] = {
        "eventFirst": event_limit,
        "catalogFirst": catalog_limit,
    }
    if updated_since is not None:
        variables["updatedAfter"] = updated_since
    return variables


def _send_json_request(
    request: Request,
    *,
    retry_rate_limit: bool = False,
) -> dict[str, object]:
    payload = ""
    for attempt in range(2 if retry_rate_limit else 1):
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read().decode("utf-8")
            break
        except HTTPError as exc:
            if exc.code == 429 and retry_rate_limit and attempt == 0:
                sleep(_retry_after_seconds(exc))
                continue
            raise SourceClientError(
                f"Source request failed with HTTP {exc.code}: {_safe_error_body(exc)}"
            ) from exc
        except URLError as exc:
            raise SourceClientError(f"Source request failed: {exc.reason}") from exc
    try:
        response_data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SourceClientError("Source response was not valid JSON") from exc
    if not isinstance(response_data, dict):
        raise SourceClientError("Source response JSON was not an object")
    errors = response_data.get("errors")
    if isinstance(errors, list) and errors:
        raise SourceClientError(f"GraphQL request returned errors: {_safe_graphql_errors(errors)}")
    return response_data


def _safe_error_body(error: HTTPError) -> str:
    body = error.read().decode("utf-8", errors="replace").strip()
    if not body:
        return error.reason
    return body[:500]


def _retry_after_seconds(error: HTTPError) -> float:
    raw_value = error.headers.get("Retry-After")
    try:
        retry_after = float(raw_value) if raw_value is not None else 1.0
    except ValueError:
        retry_after = 1.0
    return max(0.0, min(retry_after, 10.0))


def _safe_graphql_errors(errors: list[object]) -> str:
    messages: list[str] = []
    for error in errors[:3]:
        if not isinstance(error, dict):
            continue
        message = error.get("message")
        if isinstance(message, str) and message:
            messages.append(message)
    if not messages:
        return "unknown"
    return "; ".join(messages)[:500]


def _graphql_edge_nodes(response: dict[str, object], field_name: str) -> list[dict[str, object]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    field = data.get(field_name)
    if not isinstance(field, dict):
        return []
    edges = field.get("edges")
    if not isinstance(edges, list):
        return []
    nodes: list[dict[str, object]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if isinstance(node, dict):
            nodes.append(node)
    return nodes


def _rest_records(response: dict[str, object], field_name: str) -> list[dict[str, object]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    records = data.get(field_name)
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _nodes(data: object, field_name: str) -> list[dict[str, object]]:
    if not isinstance(data, dict):
        return []
    field = data.get(field_name)
    if not isinstance(field, dict):
        return []
    nodes = field.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def _display_name_from_twenty_name(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    parts = [value.get("firstName"), value.get("lastName")]
    return " ".join(str(part).strip() for part in parts if part).strip()


def _slack_user(member: dict[str, object]) -> dict[str, object]:
    profile = member.get("profile") if isinstance(member.get("profile"), dict) else {}
    display_name = profile.get("real_name") or profile.get("display_name") or member.get("name")
    return {
        "id": member.get("id"),
        "display_name": display_name,
        "email": profile.get("email"),
        "deleted": bool(member.get("deleted")),
        "is_bot": bool(member.get("is_bot")),
    }


def _linear_user(node: dict[str, object]) -> dict[str, object]:
    return {
        "id": node.get("id"),
        "display_name": node.get("name"),
        "email": node.get("email"),
    }


def _linear_team(node: dict[str, object]) -> dict[str, object]:
    return {
        "id": node.get("id"),
        "key": node.get("key"),
        "name": node.get("name"),
    }


def _linear_project(node: dict[str, object]) -> dict[str, object]:
    return {
        "id": node.get("id"),
        "name": node.get("name"),
    }


def _linear_issue(node: dict[str, object]) -> dict[str, object]:
    return {
        "id": node.get("id"),
        "identifier": node.get("identifier"),
        "title": node.get("title"),
        "description": node.get("description"),
        "url": node.get("url"),
        "team_id": _nested_id(node.get("team")),
        "project_id": _nested_id(node.get("project")),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "creator_id": _nested_id(node.get("creator")),
        "assignee_id": _nested_id(node.get("assignee")),
    }


def _linear_comment(node: dict[str, object]) -> dict[str, object]:
    issue = node.get("issue") if isinstance(node.get("issue"), dict) else {}
    return {
        "id": node.get("id"),
        "body": node.get("body"),
        "url": node.get("url"),
        "issue_id": issue.get("id"),
        "issue_identifier": issue.get("identifier"),
        "issue_title": issue.get("title"),
        "team_id": _nested_id(issue.get("team")),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "user_id": _nested_id(node.get("user")),
    }


def _nested_id(value: object) -> object:
    if not isinstance(value, dict):
        return None
    return value.get("id")
