from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RestTransport = Callable[[str, dict[str, object]], dict[str, object]]

DEFAULT_TWENTY_REST_URL = "https://api.twenty.com/rest"
DEFAULT_TWENTY_LIMIT = 1000
TWENTY_PAGE_SIZE = 200


@dataclass(frozen=True)
class TwentyTapConfig:
    api_key: str
    base_url: str = DEFAULT_TWENTY_REST_URL
    limit: int = DEFAULT_TWENTY_LIMIT

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("TWENTY_API_KEY is required")
        if self.limit <= 0:
            raise ValueError("TWENTY_LIMIT must be positive")


def main() -> None:
    try:
        config = TwentyTapConfig(
            api_key=os.environ.get("TWENTY_API_KEY", ""),
            base_url=os.environ.get("TWENTY_BASE_URL")
            or os.environ.get("TWENTY_REST_URL")
            or DEFAULT_TWENTY_REST_URL,
            limit=int(os.environ.get("TWENTY_LIMIT", str(DEFAULT_TWENTY_LIMIT))),
        )
        for message in run_twenty_tap(config):
            print(json.dumps(message, sort_keys=True))
    except Exception as exc:
        print(f"tap-gcb-twenty failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def run_twenty_tap(
    config: TwentyTapConfig,
    *,
    rest: RestTransport | None = None,
) -> list[dict[str, Any]]:
    transport = rest or rest_transport(base_url=config.base_url, api_key=config.api_key)
    companies = [
        _company_record(row) for row in _paginated_records(transport, "companies", config.limit)
    ]
    people = [_person_record(row) for row in _paginated_records(transport, "people", config.limit)]

    messages: list[dict[str, Any]] = [
        {
            "type": "SCHEMA",
            "stream": "twenty_companies",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "domainName": {"type": "string"},
                    "updated_at": {"type": "string"},
                },
            },
        }
    ]
    messages.extend(
        {"type": "RECORD", "stream": "twenty_companies", "record": record} for record in companies
    )
    messages.append(
        {
            "type": "SCHEMA",
            "stream": "twenty_people",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "object"},
                    "email": {"type": "string"},
                    "company_id": {"type": "string"},
                    "updated_at": {"type": "string"},
                },
            },
        }
    )
    messages.extend(
        {"type": "RECORD", "stream": "twenty_people", "record": record} for record in people
    )
    messages.append({"type": "STATE", "value": {"bookmarks": _bookmarks(companies, people)}})
    return messages


def rest_transport(*, base_url: str, api_key: str) -> RestTransport:
    normalized_base_url = base_url.rstrip("/")

    def _transport(path: str, params: dict[str, object]) -> dict[str, object]:
        encoded = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{normalized_base_url}/{path.lstrip('/')}"
        if encoded:
            url = f"{url}?{encoded}"
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "gcb-tap-twenty/0.1",
            },
            method="GET",
        )
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError(f"Twenty REST response for {path} is not an object")
        return parsed

    return _transport


def _paginated_records(transport: RestTransport, path: str, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    starting_after = ""
    while len(records) < limit:
        page_limit = min(TWENTY_PAGE_SIZE, limit - len(records))
        params: dict[str, object] = {"limit": page_limit}
        if starting_after:
            params["starting_after"] = starting_after
        response = transport(path, params)
        page_records = _records(response, path)
        records.extend(page_records[:page_limit])
        page_info = response.get("pageInfo")
        data = response.get("data")
        if not isinstance(page_info, dict) and isinstance(data, dict):
            page_info = data.get("pageInfo")
        has_next_page = bool(page_info.get("hasNextPage")) if isinstance(page_info, dict) else False
        next_cursor = _string(page_info.get("endCursor")) if isinstance(page_info, dict) else ""
        if not page_records or not has_next_page or not next_cursor:
            break
        starting_after = next_cursor
    return records[:limit]


def _company_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _string(row.get("id")),
        "name": _string(row.get("name")),
        "domainName": _string(row.get("domainName") or row.get("domain_name")),
        "created_at": _string(row.get("createdAt") or row.get("created_at")),
        "updated_at": _string(row.get("updatedAt") or row.get("updated_at")),
        "url": _string(row.get("url")),
    }


def _person_record(row: dict[str, Any]) -> dict[str, Any]:
    company = row.get("company") if isinstance(row.get("company"), dict) else {}
    return {
        "id": _string(row.get("id")),
        "name": _name(row.get("name")),
        "email": _email(row),
        "emails": [_email(row)] if _email(row) else [],
        "jobTitle": _string(row.get("jobTitle") or row.get("job_title")),
        "company_id": _string(row.get("company_id") or company.get("id")),
        "company_name": _string(row.get("company_name") or company.get("name")),
        "created_at": _string(row.get("createdAt") or row.get("created_at")),
        "updated_at": _string(row.get("updatedAt") or row.get("updated_at")),
        "url": _string(row.get("url")),
    }


def _records(response: dict[str, object], key: str) -> list[dict[str, Any]]:
    data = response.get("data")
    if isinstance(data, dict):
        raw = data.get(key)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    raw = response.get(key)
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _bookmarks(
    companies: list[dict[str, Any]], people: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    return {
        "twenty_companies": {"updated_at": _max_updated_at(companies)},
        "twenty_people": {"updated_at": _max_updated_at(people)},
    }


def _max_updated_at(records: list[dict[str, Any]]) -> str:
    return max((_string(record.get("updated_at")) for record in records), default="")


def _name(value: object) -> object:
    if isinstance(value, dict):
        return {
            "firstName": _string(value.get("firstName") or value.get("first_name")),
            "lastName": _string(value.get("lastName") or value.get("last_name")),
        }
    if isinstance(value, str):
        return value
    return {"firstName": "", "lastName": ""}


def _email(row: dict[str, Any]) -> str:
    for key in ("email", "primaryEmail", "primary_email", "userEmail"):
        value = _string(row.get(key))
        if value:
            return value
    emails = row.get("emails")
    if isinstance(emails, dict):
        return _string(emails.get("primaryEmail") or emails.get("primary_email"))
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, str) and item:
                return item
            if isinstance(item, dict):
                value = _string(item.get("value") or item.get("email"))
                if value:
                    return value
    return ""


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
