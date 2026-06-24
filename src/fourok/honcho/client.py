from __future__ import annotations

import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

from fourok.honcho.experiment import HonchoMessagePlan


class HonchoHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        workspace_id: str,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def health(self) -> object:
        request = Request(f"{self.base_url}/health", headers=self._headers())
        return self._send(request)

    def add_message(self, message: HonchoMessagePlan) -> object:
        payload = {
            "messages": [
                {
                    "peer_id": _honcho_resource_id(message.peer),
                    "content": message.text,
                    "metadata": message.metadata,
                }
            ]
        }
        request = Request(
            self._session_messages_url(message.session),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
            method="POST",
        )
        return self._send(request)

    def list_messages(self, session_id: str) -> object:
        request = Request(
            f"{self._session_messages_url(session_id)}/list",
            data=json.dumps({}).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
            method="POST",
        )
        return self._send(request)

    def update_message_metadata(
        self,
        *,
        session_id: str,
        message_id: str,
        metadata: dict[str, object],
    ) -> object:
        request = Request(
            f"{self._session_messages_url(session_id)}/{quote(message_id, safe='')}",
            data=json.dumps({"metadata": metadata}).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
            method="PUT",
        )
        return self._send(request)

    def search_messages(
        self,
        *,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> object:
        return self._search(
            f"{self.base_url}/v3/workspaces/{quote(self.workspace_id, safe='')}/search",
            query=query,
            filters=filters,
            limit=limit,
        )

    def search_peer(
        self,
        *,
        peer_id: str,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> object:
        peer = quote(_honcho_resource_id(peer_id), safe="")
        workspace = quote(self.workspace_id, safe="")
        return self._search(
            f"{self.base_url}/v3/workspaces/{workspace}/peers/{peer}/search",
            query=query,
            filters=filters,
            limit=limit,
        )

    def search_session(
        self,
        *,
        session_id: str,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 10,
    ) -> object:
        session = quote(_honcho_resource_id(session_id), safe="")
        workspace = quote(self.workspace_id, safe="")
        return self._search(
            f"{self.base_url}/v3/workspaces/{workspace}/sessions/{session}/search",
            query=query,
            filters=filters,
            limit=limit,
        )

    def _session_messages_url(self, session_id: str) -> str:
        workspace = quote(self.workspace_id, safe="")
        session = quote(_honcho_resource_id(session_id), safe="")
        return f"{self.base_url}/v3/workspaces/{workspace}/sessions/{session}/messages"

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _search(
        self,
        url: str,
        *,
        query: str,
        filters: dict[str, object] | None,
        limit: int,
    ) -> object:
        payload = {"query": query, "filters": filters, "limit": limit}
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(content_type="application/json"),
            method="POST",
        )
        return self._send(request)

    def _send(self, request: Request) -> object:
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()
        if not body:
            return None
        return json.loads(body.decode("utf-8"))


def _honcho_resource_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
