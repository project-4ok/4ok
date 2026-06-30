from pathlib import Path

import pytest

from fourok.etl.extract.connectors import land_singer_records, load_landed_source_records
from fourok.etl.extract.google_drive_tap import GoogleDriveTapConfig, run_google_drive_tap


def test_google_drive_tap_emits_files_and_state() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        calls.append((method, path, params))
        if path == "files":
            return {
                "files": [
                    {
                        "id": "doc-1",
                        "name": "Alpha notes",
                        "mimeType": "application/vnd.google-apps.document",
                        "createdTime": "2026-06-01T08:00:00Z",
                        "modifiedTime": "2026-06-03T09:00:00Z",
                        "webViewLink": "https://docs.google.com/document/d/doc-1/edit",
                        "owners": [{"displayName": "Olivia", "emailAddress": "olivia@example.com"}],
                        "permissions": [
                            {"id": "perm-1", "type": "user", "emailAddress": "ops@example.com"}
                        ],
                    }
                ]
            }
        if path == "files/doc-1/export":
            return "Alpha contract notes"
        raise AssertionError(path)

    messages = run_google_drive_tap(
        GoogleDriveTapConfig(access_token="token", drive_ids=("drive-1",)),
        api=fake_api,
    )

    assert [message["type"] for message in messages] == ["SCHEMA", "RECORD", "STATE"]
    assert messages[1]["stream"] == "google_drive_files"
    assert messages[1]["record"]["text"] == "Alpha contract notes"
    assert messages[1]["record"]["content_status"] == "extracted"
    assert messages[1]["record"]["export_status"] == "exported_text"
    assert messages[-1]["value"] == {
        "bookmarks": {"google_drive_files": {"modifiedTime": "2026-06-03T09:00:00Z"}}
    }
    assert calls[0] == (
        "GET",
        "files",
        {
            "pageSize": 100,
            "fields": (
                "nextPageToken,files(id,name,mimeType,createdTime,modifiedTime,"
                "webViewLink,trashed,parents,owners(displayName,emailAddress),"
                "permissions(id,type,emailAddress,domain,role))"
            ),
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "drive",
            "driveId": "drive-1",
            "q": "trashed = false",
        },
    )


def test_google_drive_tap_output_feeds_existing_source_record_adapter(tmp_path: Path) -> None:
    def fake_api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        if path == "files":
            return {
                "files": [
                    {
                        "id": "doc-1",
                        "name": "Alpha notes",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-06-03T09:00:00Z",
                        "webViewLink": "https://docs.google.com/document/d/doc-1/edit",
                        "permissions": [{"type": "group", "emailAddress": "ops@example.com"}],
                    }
                ]
            }
        return "Alpha contract notes"

    messages = run_google_drive_tap(
        GoogleDriveTapConfig(access_token="token", drive_ids=()),
        api=fake_api,
    )
    singer_file = tmp_path / "drive.singer.jsonl"
    singer_file.write_text(
        "\n".join(__import__("json").dumps(message, sort_keys=True) for message in messages) + "\n",
        encoding="utf-8",
    )

    report = land_singer_records(singer_file, tmp_path / "landing")
    records = load_landed_source_records(tmp_path / "landing", stream="google_drive_files")

    assert report.streams == {"google_drive_files": 1}
    assert records[0].source_ref == "google_drive:file:doc-1"
    assert records[0].body == "Alpha contract notes"


def test_google_drive_tap_emits_unsupported_image_metadata_without_body_download() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        calls.append((method, path, dict(params)))
        if path == "files":
            return {
                "files": [
                    {
                        "id": "image-1",
                        "name": "Boiler room photo",
                        "mimeType": "image/png",
                        "createdTime": "2026-06-08T10:00:00Z",
                        "modifiedTime": "2026-06-09T11:00:00Z",
                        "webViewLink": "https://drive.google.com/file/d/image-1/view",
                        "parents": ["folder-maintenance"],
                        "owners": [{"displayName": "Olivia", "emailAddress": "olivia@example.com"}],
                        "permissions": [{"id": "perm-image", "type": "user"}],
                    }
                ]
            }
        raise AssertionError((method, path, params))

    messages = run_google_drive_tap(
        GoogleDriveTapConfig(access_token="token", drive_ids=()),
        api=fake_api,
    )

    assert [message["type"] for message in messages] == ["SCHEMA", "RECORD", "STATE"]
    assert messages[1]["record"] == {
        "id": "image-1",
        "name": "Boiler room photo",
        "mimeType": "image/png",
        "createdTime": "2026-06-08T10:00:00Z",
        "modifiedTime": "2026-06-09T11:00:00Z",
        "webViewLink": "https://drive.google.com/file/d/image-1/view",
        "owners": [{"displayName": "Olivia", "emailAddress": "olivia@example.com"}],
        "parents": ["folder-maintenance"],
        "permissions": [{"id": "perm-image", "type": "user"}],
        "folder_path": "My Drive",
        "parent_refs": ["google_drive:folder:folder-maintenance"],
        "trashed": False,
        "text": "",
        "content_status": "metadata_only",
        "export_status": "unsupported_mime_type",
    }
    assert [call[1] for call in calls] == ["files"]


def test_google_drive_tap_discovers_my_drive_recursively_and_exports_meet_transcript() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        calls.append((path, dict(params)))
        if path == "files" and params["q"] == "'root' in parents and trashed = false":
            return {
                "files": [
                    {
                        "id": "meet-folder",
                        "name": "Meet Recordings",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["root"],
                        "modifiedTime": "2026-06-09T08:00:00Z",
                    }
                ]
            }
        if path == "files" and params["q"] == "'meet-folder' in parents and trashed = false":
            return {
                "files": [
                    {
                        "id": "transcript-doc",
                        "name": "Gemini transcript",
                        "mimeType": "application/vnd.google-apps.document",
                        "parents": ["meet-folder"],
                        "modifiedTime": "2026-06-09T09:00:00Z",
                        "webViewLink": "https://docs.google.com/document/d/transcript-doc/edit",
                        "owners": [{"displayName": "Olivia", "emailAddress": "olivia@example.com"}],
                    }
                ]
            }
        if path == "files/transcript-doc/export":
            assert params == {"mimeType": "text/plain"}
            return "Meeting transcript text exported from Google Docs."
        raise AssertionError((method, path, params))

    messages = run_google_drive_tap(
        GoogleDriveTapConfig(access_token="token"),
        api=fake_api,
    )

    records = [message["record"] for message in messages if message["type"] == "RECORD"]
    assert records == [
        {
            "id": "transcript-doc",
            "name": "Gemini transcript",
            "mimeType": "application/vnd.google-apps.document",
            "createdTime": "",
            "modifiedTime": "2026-06-09T09:00:00Z",
            "webViewLink": "https://docs.google.com/document/d/transcript-doc/edit",
            "owners": [{"displayName": "Olivia", "emailAddress": "olivia@example.com"}],
            "parents": ["meet-folder"],
            "permissions": [],
            "folder_path": "My Drive/Meet Recordings",
            "parent_refs": ["google_drive:folder:meet-folder"],
            "trashed": False,
            "text": "Meeting transcript text exported from Google Docs.",
            "content_status": "extracted",
            "export_status": "exported_text",
        }
    ]
    assert [call[1]["q"] for call in calls if call[0] == "files"] == [
        "'root' in parents and trashed = false",
        "'meet-folder' in parents and trashed = false",
    ]


def test_google_drive_tap_keeps_metadata_only_file_when_content_unavailable() -> None:
    def fake_api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        if path == "files":
            return {
                "files": [
                    {
                        "id": "folder-1",
                        "name": "Assets",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["root"],
                    },
                    {
                        "id": "image-1",
                        "name": "Whiteboard photo",
                        "mimeType": "image/png",
                        "parents": ["folder-1"],
                        "owners": [{"emailAddress": "olivia@example.com"}],
                    },
                ]
            }
        raise AssertionError((method, path, params))

    messages = run_google_drive_tap(
        GoogleDriveTapConfig(access_token="token"),
        api=fake_api,
    )

    records = [message["record"] for message in messages if message["type"] == "RECORD"]
    assert records[0]["id"] == "image-1"
    assert records[0]["text"] == ""
    assert records[0]["content_status"] == "metadata_only"
    assert records[0]["export_status"] == "unsupported_mime_type"
    assert records[0]["folder_path"] == "My Drive/Assets"


def test_google_drive_tap_requires_access_token() -> None:
    with pytest.raises(ValueError, match="Google Drive access token is required"):
        GoogleDriveTapConfig(access_token="")
