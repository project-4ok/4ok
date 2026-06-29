from pathlib import Path

from fourok.etl.extract.connectors import (
    google_drive_file_source_record_from_raw,
    land_singer_records,
    load_google_drive_source_records,
    load_landed_source_records,
)
from fourok.etl.extract.google_drive_tap import GoogleDriveTapConfig, run_google_drive_tap
from fourok.governance.context import GovernedContext
from fourok.governance.policy import PrincipalContext

FIXTURES = Path(__file__).parents[2] / "fixtures" / "connectors"
SINGER_GOOGLE_DRIVE_DOCS = FIXTURES / "singer_google_drive_docs.jsonl"


def test_google_drive_singer_records_map_to_document_source_records() -> None:
    source_records = load_google_drive_source_records(SINGER_GOOGLE_DRIVE_DOCS)

    assert [record.source_ref for record in source_records] == [
        "google_drive:file:drive-file-alpha-contract"
    ]
    record = source_records[0]
    assert record.source_system == "google_drive"
    assert record.record_type == "document"
    assert record.title == "Alpha cancellation contract notes"
    assert record.body == (
        "Alpha Hausverwaltung contract notes confirm cancellation review and "
        "refund evidence requirements."
    )
    assert record.source_url.endswith("/drive-file-alpha-contract/edit")
    assert record.permission_refs == ("google_drive:permission:group:ops@example.com",)
    assert record.permission_snapshot_status == "current"
    assert record.identity_refs == ("google_drive:email:olivia@example.com",)
    assert record.metadata == {
        "content_status": "extracted",
        "export_status": "exported_text",
        "file_id": "drive-file-alpha-contract",
        "mime_type": "application/vnd.google-apps.document",
        "owner_refs": ["google_drive:email:olivia@example.com"],
        "raw_metadata_ref": "google_drive:file:drive-file-alpha-contract",
        "source_object_type": "file",
    }


def test_google_drive_raw_landing_can_be_reloaded_into_source_records() -> None:
    landing_dir = Path(".local/test-artifacts/connectors/google-drive-raw-landing")
    if landing_dir.exists():
        for path in landing_dir.glob("*"):
            path.unlink()

    report = land_singer_records(SINGER_GOOGLE_DRIVE_DOCS, landing_dir)
    records = load_landed_source_records(landing_dir, stream="google_drive_files")

    assert report.record_count == 1
    assert report.streams == {"google_drive_files": 1}
    assert report.schema_messages == 1
    assert report.state_messages == 1
    assert records[0].source_ref == "google_drive:file:drive-file-alpha-contract"


def test_google_drive_file_adapter_imports_unsupported_image_as_metadata_only_record() -> None:
    record = google_drive_file_source_record_from_raw(
        {
            "id": "image-1",
            "name": "Boiler room photo",
            "mimeType": "image/png",
            "createdTime": "2026-06-08T10:00:00Z",
            "modifiedTime": "2026-06-09T11:00:00Z",
            "webViewLink": "https://drive.google.com/file/d/image-1/view",
            "parents": ["folder-maintenance"],
            "folder_path": "My Drive/Meet Recordings",
            "parent_refs": ["google_drive:folder:folder-maintenance"],
            "owners": [{"displayName": "Olivia", "emailAddress": "olivia@example.com"}],
            "permissions": [
                {"id": "perm-image", "type": "user", "emailAddress": "ops@example.com"}
            ],
            "text": "",
            "content_status": "metadata_only",
            "export_status": "unsupported_mime_type",
        }
    )
    context = GovernedContext()

    context.ingest_source_records([record])

    assert record.source_ref == "google_drive:file:image-1"
    assert record.body == (
        "Google Drive metadata-only file\n"
        "Name: Boiler room photo\n"
        "MIME type: image/png\n"
        "Folder path: My Drive/Meet Recordings\n"
        "Owner: Olivia <olivia@example.com>\n"
        "Folder: folder-maintenance\n"
        "Web link: https://drive.google.com/file/d/image-1/view\n"
        "Content status: metadata_only\n"
        "Export status: unsupported_mime_type"
    )
    assert record.permission_refs == ("google_drive:permission:perm-image",)
    assert record.identity_refs == ("google_drive:email:olivia@example.com",)
    assert record.metadata == {
        "content_status": "metadata_only",
        "export_status": "unsupported_mime_type",
        "file_id": "image-1",
        "folder_path": "My Drive/Meet Recordings",
        "folder_refs": ["folder-maintenance"],
        "mime_type": "image/png",
        "owner_refs": ["google_drive:email:olivia@example.com"],
        "parent_refs": ["google_drive:folder:folder-maintenance"],
        "raw_metadata_ref": "google_drive:file:image-1",
        "source_object_type": "file",
    }
    assert record.raw["text"] == ""
    assert [unit["prepared_text"] for unit in context.retrieval_units()] == [
        (
            "Boiler room photo Google Drive metadata-only file Name: Boiler room photo "
            "MIME type: image/png Folder path: My Drive/Meet Recordings "
            "Owner: Olivia <olivia@example.com> Folder: folder-maintenance "
            "Web link: https://drive.google.com/file/d/image-1/view Content status: metadata_only "
            "Export status: unsupported_mime_type"
        )
    ]
    assert [
        result.source_ref
        for result in context.search_context(
            "image/png Olivia Meet Recordings",
            principal=PrincipalContext(
                human_id="human:ops",
                agent_id="agent:retrieval",
                roles=("google_drive:permission:perm-image",),
            ),
        ).results
    ] == ["google_drive:file:image-1"]


def test_google_drive_domain_permission_records_become_searchable_for_allowed_role() -> None:
    record = google_drive_file_source_record_from_raw(
        {
            "id": "buena-architecture-overview",
            "name": "Buena Architecture Overview",
            "mimeType": "application/vnd.google-apps.document",
            "text": "Buena Architecture Overview explains the live ingestion flow.",
            "permissions": [
                {
                    "type": "domain",
                    "domain": "buena.example",
                    "role": "reader",
                }
            ],
        }
    )
    context = GovernedContext()

    context.ingest_source_records([record])

    assert record.permission_refs == ("google_drive:permission:domain:buena.example",)
    assert record.permission_snapshot_status == "current"
    assert record.effective_lifecycle_state == "active"
    assert context.source_records()[0]["lifecycle_state"] == "active"
    assert [unit["source_ref"] for unit in context.retrieval_units()] == [
        "google_drive:file:buena-architecture-overview"
    ]
    denied = context.search_context("Buena Architecture Overview").results
    allowed = context.search_context(
        "Buena Architecture Overview",
        principal=PrincipalContext(
            human_id="human:buena",
            agent_id="agent:retrieval",
            roles=("google_drive:permission:domain:buena.example",),
        ),
    ).results
    assert denied == []
    assert [result.source_ref for result in allowed] == [
        "google_drive:file:buena-architecture-overview"
    ]


def test_google_drive_file_adapter_uses_operator_scope_when_drive_omits_permissions() -> None:
    record = google_drive_file_source_record_from_raw(
        {
            "id": "buena-progress-update",
            "name": "Buena Progress Update",
            "mimeType": "application/vnd.google-apps.document",
            "text": "Buena Architecture Overview explains the current prototype architecture.",
            "permissions": [],
            "owners": [],
        }
    )
    context = GovernedContext()

    context.ingest_source_records([record])

    assert record.permission_refs == ("operator",)
    assert record.permission_snapshot_status == "current"
    assert record.effective_lifecycle_state == "active"
    assert context.source_records()[0]["lifecycle_state"] == "active"
    assert [unit["source_ref"] for unit in context.retrieval_units()] == [
        "google_drive:file:buena-progress-update"
    ]
    assert [
        result.source_ref
        for result in context.search_context("Buena Architecture Overview").results
    ] == ["google_drive:file:buena-progress-update"]


def test_google_drive_tap_paginates_file_listing_until_configured_limit() -> None:
    calls: list[dict[str, object]] = []

    def fake_api(method: str, path: str, params: dict[str, object]) -> dict[str, object] | str:
        calls.append({"method": method, "path": path, "params": dict(params)})
        if path == "files" and params.get("pageToken") is None:
            return {
                "nextPageToken": "page-2",
                "files": [
                    {
                        "id": f"file-{index}",
                        "name": f"Doc {index}",
                        "mimeType": "text/plain",
                        "modifiedTime": f"2026-06-09T00:{index:02d}:00Z",
                    }
                    for index in range(100)
                ],
            }
        if path == "files" and params.get("pageToken") == "page-2":
            return {
                "files": [
                    {
                        "id": f"file-{index}",
                        "name": f"Doc {index}",
                        "mimeType": "text/plain",
                        "modifiedTime": f"2026-06-09T01:{index - 100:02d}:00Z",
                    }
                    for index in range(100, 150)
                ],
            }
        if params.get("alt") == "media":
            return f"text for {path}"
        raise AssertionError((method, path, params))

    messages = run_google_drive_tap(
        GoogleDriveTapConfig(access_token="token", limit=150),
        api=fake_api,
    )

    assert sum(1 for message in messages if message.get("type") == "RECORD") == 150
    file_list_params = [call["params"] for call in calls if call["path"] == "files"]
    page_sizes: list[object] = []
    page_tokens: list[object] = []
    for params in file_list_params:
        assert isinstance(params, dict)
        page_sizes.append(params.get("pageSize"))
        page_tokens.append(params.get("pageToken"))
    assert page_sizes == [100, 50]
    assert page_tokens == [None, "page-2"]


def test_google_drive_tap_default_limit_stays_bounded_because_files_are_downloaded() -> None:
    assert GoogleDriveTapConfig(access_token="token").limit == 100


def test_committed_meltano_config_wires_google_drive_fixture_job() -> None:
    meltano_config = Path(__file__).parents[3] / "deploy" / "meltano" / "meltano.yml"
    config = meltano_config.read_text(encoding="utf-8")

    assert "tap-fourok-google-drive-fixture" in config
    assert "../../tests/fixtures/connectors/singer_google_drive_docs.jsonl" in config
    assert "singer-google-drive-fixture-to-raw" in config
    assert "tap-fourok-google-drive-fixture target-fourok-raw-jsonl" in config
