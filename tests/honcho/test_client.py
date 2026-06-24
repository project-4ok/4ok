from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request

import pytest

from gcb.honcho.client import HonchoHttpClient
from gcb.honcho.experiment import HonchoMessagePlan


def test_honcho_client_posts_message_batch_with_v3_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response([{"id": "msg-1"}])

    monkeypatch.setattr("gcb.honcho.client.urlopen", fake_urlopen)
    client = HonchoHttpClient(
        base_url="http://honcho:8000/",
        workspace_id="gcb internal",
        api_key="secret-token",
        timeout_seconds=2.5,
    )

    response = client.add_message(
        HonchoMessagePlan(
            peer="linear:team:ops",
            session="slack_U123456:linear:2026-06",
            text="hello",
            metadata={"source_ref": "linear:issue:ABC-123"},
        )
    )

    assert response == [{"id": "msg-1"}]
    assert captured["url"] == (
        "http://honcho:8000/v3/workspaces/gcb%20internal/"
        "sessions/slack_U123456_linear_2026-06/messages"
    )
    assert captured["timeout"] == 2.5
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["body"] == {
        "messages": [
            {
                "peer_id": "linear_team_ops",
                "content": "hello",
                "metadata": {"source_ref": "linear:issue:ABC-123"},
            }
        ]
    }


def test_honcho_client_updates_message_metadata_with_v3_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response({"id": "msg-old", "metadata": captured["body"]["metadata"]})

    monkeypatch.setattr("gcb.honcho.client.urlopen", fake_urlopen)
    client = HonchoHttpClient(
        base_url="http://honcho:8000/",
        workspace_id="gcb internal",
        api_key="secret-token",
        timeout_seconds=2.5,
    )

    response = client.update_message_metadata(
        session_id="slack_U123456:linear:2026-06",
        message_id="msg-old",
        metadata={"source_ref": "linear:issue:ABC-123", "source_status": "superseded"},
    )

    assert response == {
        "id": "msg-old",
        "metadata": {"source_ref": "linear:issue:ABC-123", "source_status": "superseded"},
    }
    assert captured["url"] == (
        "http://honcho:8000/v3/workspaces/gcb%20internal/"
        "sessions/slack_U123456_linear_2026-06/messages/msg-old"
    )
    assert captured["method"] == "PUT"
    assert captured["timeout"] == 2.5
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["body"] == {
        "metadata": {"source_ref": "linear:issue:ABC-123", "source_status": "superseded"}
    }


def test_honcho_client_searches_workspace_with_v3_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response([{"id": "msg-1", "metadata": {"source_ref": "linear:issue:ABC-123"}}])

    monkeypatch.setattr("gcb.honcho.client.urlopen", fake_urlopen)
    client = HonchoHttpClient(
        base_url="http://honcho:8000/",
        workspace_id="gcb internal",
        api_key="secret-token",
        timeout_seconds=2.5,
    )

    response = client.search_messages(
        query="ask robin meeting",
        filters={"metadata.source_status": "active"},
        limit=3,
    )

    assert response == [{"id": "msg-1", "metadata": {"source_ref": "linear:issue:ABC-123"}}]
    assert captured["url"] == "http://honcho:8000/v3/workspaces/gcb%20internal/search"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 2.5
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["body"] == {
        "query": "ask robin meeting",
        "filters": {"metadata.source_status": "active"},
        "limit": 3,
    }


def test_honcho_client_searches_peer_with_v3_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response([{"id": "msg-1"}])

    monkeypatch.setattr("gcb.honcho.client.urlopen", fake_urlopen)
    client = HonchoHttpClient(base_url="http://honcho:8000/", workspace_id="gcb internal")

    response = client.search_peer(peer_id="slack:U123456", query="meeting", limit=2)

    assert response == [{"id": "msg-1"}]
    assert captured["url"] == (
        "http://honcho:8000/v3/workspaces/gcb%20internal/peers/slack_U123456/search"
    )
    assert captured["method"] == "POST"
    assert captured["body"] == {"query": "meeting", "filters": None, "limit": 2}


def test_honcho_client_searches_session_with_v3_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response([{"id": "msg-1"}])

    monkeypatch.setattr("gcb.honcho.client.urlopen", fake_urlopen)
    client = HonchoHttpClient(base_url="http://honcho:8000/", workspace_id="gcb internal")

    response = client.search_session(
        session_id="slack_U123456:linear:2026-06",
        query="meeting",
        limit=2,
    )

    assert response == [{"id": "msg-1"}]
    assert captured["url"] == (
        "http://honcho:8000/v3/workspaces/gcb%20internal/"
        "sessions/slack_U123456_linear_2026-06/search"
    )
    assert captured["method"] == "POST"
    assert captured["body"] == {"query": "meeting", "filters": None, "limit": 2}


def test_honcho_client_health_raises_when_server_is_unavailable(monkeypatch) -> None:
    def fake_urlopen(request: Request, timeout: float):
        raise URLError("connection refused")

    monkeypatch.setattr("gcb.honcho.client.urlopen", fake_urlopen)
    client = HonchoHttpClient(base_url="http://honcho:8000", workspace_id="gcb")

    with pytest.raises(URLError):
        client.health()


class _Response:
    def __init__(self, payload: object):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")
