from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DriveApi = Callable[[str, str, dict[str, object]], dict[str, object] | str]

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
TEXT_MIME_TYPES = {"text/plain", "text/markdown"}
DEFAULT_GOOGLE_WORKSPACE_LIMIT = 100
GOOGLE_DRIVE_PAGE_SIZE = 100


@dataclass(frozen=True)
class GoogleDriveTapConfig:
    access_token: str
    drive_ids: tuple[str, ...] = ()
    limit: int = DEFAULT_GOOGLE_WORKSPACE_LIMIT

    def __post_init__(self) -> None:
        if not self.access_token:
            raise ValueError("Google Drive access token is required")
        if self.limit <= 0:
            raise ValueError("GOOGLE_WORKSPACE_LIMIT must be positive")


def main() -> None:
    try:
        config = GoogleDriveTapConfig(
            access_token=_access_token_from_env(),
            drive_ids=tuple(_split_csv(os.environ.get("GOOGLE_WORKSPACE_DRIVE_IDS", ""))),
            limit=int(
                os.environ.get("GOOGLE_WORKSPACE_LIMIT", str(DEFAULT_GOOGLE_WORKSPACE_LIMIT))
            ),
        )
        for message in run_google_drive_tap(config):
            print(json.dumps(message, sort_keys=True))
    except Exception as exc:
        print(f"tap-gcb-google-drive failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def run_google_drive_tap(
    config: GoogleDriveTapConfig,
    *,
    api: DriveApi | None = None,
) -> list[dict[str, Any]]:
    drive_api = api or drive_api_transport(access_token=config.access_token)
    files = [
        _file_record(file, drive_api)
        for drive_id in (config.drive_ids or ("",))
        for file in _list_files(drive_api, drive_id=drive_id, limit=config.limit)
    ]

    messages: list[dict[str, Any]] = [
        {
            "type": "SCHEMA",
            "stream": "google_drive_files",
            "schema": {"type": "object"},
        }
    ]
    messages.extend(
        {"type": "RECORD", "stream": "google_drive_files", "record": record} for record in files
    )
    messages.append(
        {
            "type": "STATE",
            "value": {
                "bookmarks": {"google_drive_files": {"modifiedTime": _max_modified_time(files)}}
            },
        }
    )
    return messages


def drive_api_transport(*, access_token: str) -> DriveApi:
    def _api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        encoded = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{DRIVE_API_URL}/{path.lstrip('/')}"
        if encoded:
            url = f"{url}?{encoded}"
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "gcb-tap-google-drive/0.1",
            },
            method=method,
        )
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        if path.endswith("/export") or params.get("alt") == "media":
            return body
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError(f"Google Drive response for {path} is not an object")
        return parsed

    return _api


def _access_token_from_env() -> str:
    explicit = os.environ.get("GOOGLE_WORKSPACE_ACCESS_TOKEN")
    if explicit:
        return explicit
    client = json.loads(os.environ.get("GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON", "{}"))
    refresh_token = os.environ.get("GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN", "")
    client_id = _string(client.get("client_id") or client.get("installed", {}).get("client_id"))
    client_secret = _string(
        client.get("client_secret") or client.get("installed", {}).get("client_secret")
    )
    if not client_id or not client_secret or not refresh_token:
        raise ValueError("Google Workspace OAuth client and refresh token are required")
    body = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    token = parsed.get("access_token") if isinstance(parsed, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("Google OAuth token response did not include access_token")
    return token


def _list_files(api: DriveApi, *, drive_id: str, limit: int) -> list[dict[str, Any]]:
    if not drive_id:
        return _list_my_drive_files(api, limit=limit)
    return _list_paged_files(api, drive_id=drive_id, parent_id="", limit=limit)


def _list_my_drive_files(api: DriveApi, *, limit: int) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    folder_paths = {"root": "My Drive"}
    pending_folders = ["root"]
    seen_folders: set[str] = set()

    while pending_folders and len(files) < limit:
        folder_id = pending_folders.pop(0)
        if folder_id in seen_folders:
            continue
        seen_folders.add(folder_id)
        children = _list_paged_files(api, drive_id="", parent_id=folder_id, limit=limit)
        for child in children:
            file_id = _string(child.get("id"))
            mime_type = _string(child.get("mimeType"))
            parents = _string_list(child.get("parents"))
            folder_path = _folder_path_for_parents(parents, folder_paths)
            if mime_type == GOOGLE_FOLDER_MIME_TYPE:
                if file_id:
                    folder_paths[file_id] = _join_folder_path(
                        folder_path, _string(child.get("name"))
                    )
                    pending_folders.append(file_id)
                continue
            child["folder_path"] = folder_path
            child["parent_refs"] = [
                f"google_drive:folder:{parent_id}" for parent_id in parents if parent_id != "root"
            ]
            files.append(child)
            if len(files) >= limit:
                break
    return files[:limit]


def _list_paged_files(
    api: DriveApi, *, drive_id: str, parent_id: str, limit: int
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while len(files) < limit:
        params: dict[str, object] = {
            "pageSize": min(GOOGLE_DRIVE_PAGE_SIZE, limit - len(files)),
            "fields": (
                "nextPageToken,files(id,name,mimeType,createdTime,modifiedTime,"
                "webViewLink,trashed,parents,owners(displayName,emailAddress),"
                "permissions(id,type,emailAddress,domain,role))"
            ),
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "q": _list_query(parent_id),
        }
        if page_token:
            params["pageToken"] = page_token
        if drive_id:
            params.update({"corpora": "drive", "driveId": drive_id})
        response = api("GET", "files", params)
        if not isinstance(response, dict):
            break
        page_files = response.get("files")
        if not isinstance(page_files, list):
            break
        files.extend(file for file in page_files if isinstance(file, dict))
        page_token = _string(response.get("nextPageToken")) or None
        if not page_token:
            break
    return files[:limit]


def _file_record(file: dict[str, Any], api: DriveApi) -> dict[str, Any]:
    file_id = _string(file.get("id"))
    mime_type = _string(file.get("mimeType"))
    text, export_status = _file_text(file_id=file_id, mime_type=mime_type, api=api)
    return {
        "id": file_id,
        "name": _string(file.get("name")),
        "mimeType": mime_type,
        "createdTime": _string(file.get("createdTime")),
        "modifiedTime": _string(file.get("modifiedTime")),
        "webViewLink": _string(file.get("webViewLink")),
        "owners": file.get("owners") if isinstance(file.get("owners"), list) else [],
        "parents": _string_list(file.get("parents")),
        "permissions": _permissions(file.get("permissions")),
        "folder_path": _string(file.get("folder_path")),
        "parent_refs": _string_list(file.get("parent_refs")),
        "trashed": file.get("trashed") is True,
        "text": text,
        "content_status": "extracted" if text else "metadata_only",
        "export_status": export_status,
    }


def _file_text(*, file_id: str, mime_type: str, api: DriveApi) -> tuple[str, str]:
    if not file_id:
        return "", "missing_file_id"
    if mime_type == GOOGLE_DOC_MIME_TYPE:
        try:
            result = api("GET", f"files/{file_id}/export", {"mimeType": "text/plain"})
        except Exception:
            return "", "export_unavailable"
        return (
            (result, "exported_text")
            if isinstance(result, str) and result
            else ("", "export_unavailable")
        )
    if mime_type in TEXT_MIME_TYPES:
        try:
            result = api("GET", f"files/{file_id}", {"alt": "media"})
        except Exception:
            return "", "download_unavailable"
        return (
            (result, "downloaded_text")
            if isinstance(result, str) and result
            else ("", "download_unavailable")
        )
    return "", "unsupported_mime_type"


def _max_modified_time(records: list[dict[str, Any]]) -> str:
    return max((_string(record.get("modifiedTime")) for record in records), default="")


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _permissions(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    permissions = []
    for item in value:
        if not isinstance(item, dict):
            continue
        permissions.append(
            {
                key: text
                for key in ("id", "type", "emailAddress", "domain", "role")
                if (text := _string(item.get(key)))
            }
        )
    return permissions


def _list_query(parent_id: str) -> str:
    if parent_id:
        return f"'{parent_id}' in parents and trashed = false"
    return "trashed = false"


def _folder_path_for_parents(parents: list[str], folder_paths: dict[str, str]) -> str:
    for parent_id in parents:
        if parent_id in folder_paths:
            return folder_paths[parent_id]
    return "My Drive"


def _join_folder_path(parent_path: str, folder_name: str) -> str:
    if not folder_name:
        return parent_path
    return f"{parent_path}/{folder_name}"


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
