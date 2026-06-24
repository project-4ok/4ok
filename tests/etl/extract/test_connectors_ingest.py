from pathlib import Path

import pytest

from fourok.etl.extract.connectors import (
    ConnectorPayloadError,
    gmail_source_record_from_raw,
    land_singer_records,
    load_gmail_source_records,
    load_landed_email_messages,
    load_landed_source_records,
    load_singer_source_records,
    load_slack_source_records,
    slack_message_source_record_from_raw,
)
from fourok.etl.extract.fixture_tap import main as fixture_tap_main
from fourok.etl.extract.raw_jsonl_target import main as raw_jsonl_target_main
from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.load.source_metadata import source_metadata, store_source_records
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext
from fourok.governance.state import create_governed_context_state

FIXTURES = Path(__file__).parents[3] / "fixtures" / "connectors"
SINGER_EMAILS = FIXTURES / "singer_email_messages.jsonl"
SINGER_SLACK_MESSAGES = FIXTURES / "singer_slack_messages.jsonl"


def _source_record_legacy_fields(row: dict[str, object]) -> dict[str, object]:
    keys = [
        "source_ref",
        "source_system",
        "source_id",
        "record_type",
        "source_url",
        "thread_ref",
        "permission_refs",
        "permission_snapshot_status",
        "attachment_refs",
        "identity_refs",
        "lifecycle_state",
    ]
    return {key: row[key] for key in keys}


def test_singer_email_records_feed_governed_pipeline() -> None:
    source_records = load_singer_source_records(SINGER_EMAILS)
    context = GovernedContext()
    context.ingest_source_records(source_records)

    response = context.search_context(
        "refund cancellation iban",
        principal=PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
        limit=3,
    )
    stored_source_records = context.source_records()

    assert [result.source_ref for result in response.results][:1] == [
        "singer:email_messages:msg-001"
    ]
    assert "DE89370400440532013000" in str(response)
    assert not hasattr(response, "sensitive_tokens")
    assert stored_source_records[0]["source_system"] == "gmail"
    assert stored_source_records[0]["source_url"].endswith("#inbox/msg-001")
    assert stored_source_records[0]["thread_ref"] == "thread-001"
    assert stored_source_records[0]["permission_refs"] == '["group:finance"]'
    assert stored_source_records[0]["permission_snapshot_status"] == "current"
    assert stored_source_records[0]["attachment_refs"] == '["attachment:refund-form"]'
    assert stored_source_records[0]["identity_refs"] == (
        '["gmail:email:support@example.com", "gmail:email:finance@example.com"]'
    )


def test_source_metadata_resolves_open_target_without_raw_content() -> None:
    source_records = load_singer_source_records(SINGER_EMAILS)
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        records=source_records,
    )

    metadata = source_metadata(
        state.engine,
        state.source_records,
        source_ref="singer:email_messages:msg-001",
        principal=PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
        group_inheritance={},
    )
    denied = source_metadata(
        state.engine,
        state.source_records,
        source_ref="singer:email_messages:msg-001",
        principal=PrincipalContext(
            human_id="human:support-1",
            agent_id="agent:context-helper",
            roles=("support",),
        ),
        group_inheritance={},
    )

    assert metadata == {
        "status": "allowed",
        "source_ref": "singer:email_messages:msg-001",
        "source_system": "gmail",
        "source_id": "msg-001",
        "record_type": "email",
        "source_url": "https://mail.google.com/mail/u/0/#inbox/msg-001",
        "thread_ref": "thread-001",
        "attachment_refs": ["attachment:refund-form"],
        "lifecycle_state": "active",
    }
    assert "DE89370400440532013000" not in str(metadata)
    assert denied == {
        "status": "denied",
        "source_ref": "singer:email_messages:msg-001",
        "reason": "source_permission_denied",
    }


def test_singer_source_identities_are_captured_without_canonical_merging() -> None:
    source_records = load_singer_source_records(SINGER_EMAILS)
    context = GovernedContext()
    context.ingest_source_records(source_records)

    identities = context.source_identities()

    assert {
        (identity["source_ref"], identity["identity_ref"], identity["identity_type"])
        for identity in identities
    } >= {
        (
            "singer:email_messages:msg-001",
            "gmail:email:support@example.com",
            "sender",
        ),
        (
            "singer:email_messages:msg-001",
            "gmail:email:finance@example.com",
            "recipient",
        ),
    }
    assert all("canonical" not in identity for identity in identities)


def test_singer_raw_landing_can_be_reloaded_into_email_messages(tmp_path: Path) -> None:
    report = land_singer_records(SINGER_EMAILS, tmp_path)
    messages = load_landed_email_messages(tmp_path)
    source_records = load_landed_source_records(tmp_path)

    assert report.record_count == 2
    assert report.streams == {"email_messages": 2}
    assert report.schema_messages == 1
    assert report.state_messages == 1
    assert [message.source_ref for message in messages] == [
        "singer:email_messages:msg-001",
        "singer:email_messages:msg-002",
    ]
    assert [record.thread_ref for record in source_records] == ["thread-001", "thread-002"]


def test_slack_singer_messages_feed_source_record_adapter() -> None:
    source_records = load_slack_source_records(SINGER_SLACK_MESSAGES)

    assert [record.source_ref for record in source_records] == [
        "slack:message:C123456:1717236000.000000",
        "slack:message:C123456:1717236300.000000",
    ]
    assert [record.record_type for record in source_records] == ["message", "message"]
    assert source_records[0].source_system == "slack"
    assert source_records[0].source_id == "C123456:1717236000.000000"
    assert source_records[0].title == "#customer-success"
    assert (
        source_records[0].body == "Customer Alpha asked whether the cancellation invoice was final."
    )
    assert source_records[0].author_ref == "slack:user:U123456"
    assert source_records[0].thread_ref == "slack:thread:C123456:1717235900.000000"
    assert source_records[0].source_url.endswith("/p1717236000000000")
    assert source_records[0].identity_refs == ("slack:user:U123456",)
    assert source_records[0].metadata == {
        "channel_id": "C123456",
        "channel_name": "customer-success",
        "source_object_type": "message",
        "team_id": "T123456",
        "user_name": "Olivia Example",
    }


def test_slack_raw_landing_can_be_reloaded_into_source_records() -> None:
    landing_dir = Path(".local/test-artifacts/connectors/slack-raw-landing")
    if landing_dir.exists():
        for path in landing_dir.glob("*"):
            path.unlink()

    report = land_singer_records(SINGER_SLACK_MESSAGES, landing_dir)
    source_records = load_landed_source_records(landing_dir, stream="slack_messages")

    assert report.record_count == 2
    assert report.streams == {"slack_messages": 2}
    assert report.schema_messages == 1
    assert report.state_messages == 1
    assert [record.source_system for record in source_records] == ["slack", "slack"]
    assert [record.thread_ref for record in source_records] == [
        "slack:thread:C123456:1717235900.000000",
        "slack:thread:C123456:1717235900.000000",
    ]


def test_slack_adapter_rejects_malformed_payload_before_source_records() -> None:
    with pytest.raises(
        ValueError,
        match="Slack message record requires channel_id and ts",
    ):
        slack_message_source_record_from_raw({"text": "missing ids"})


def test_gmail_raw_record_maps_to_restricted_source_record_by_default() -> None:
    record = gmail_source_record_from_raw(
        {
            "id": "gmail-msg-1",
            "threadId": "thread-1",
            "subject": "Refund pilot",
            "snippet": "Customer sent refund IBAN DE89370400440532013000",
            "from": "customer@example.com",
            "to": ["finance@example.com"],
            "internalDate": "1716500000000",
            "labelIds": ["INBOX"],
            "payload": {
                "parts": [
                    {
                        "filename": "refund.pdf",
                        "body": {"attachmentId": "att-1"},
                    }
                ]
            },
        }
    )

    assert record.source_ref == "gmail:messages:gmail-msg-1"
    assert record.source_system == "gmail"
    assert record.source_id == "gmail-msg-1"
    assert record.thread_ref == "thread-1"
    assert record.source_url == "https://mail.google.com/mail/u/0/#all/gmail-msg-1"
    assert record.body == "Customer sent refund IBAN DE89370400440532013000"
    assert record.attachment_refs == ("att-1",)
    assert record.permission_snapshot_status == "missing"
    assert record.effective_lifecycle_state == "restricted"
    assert record.identity_refs == (
        "gmail:email:customer@example.com",
        "gmail:email:finance@example.com",
    )


def test_gmail_singer_adapter_rejects_malformed_payload_before_source_records(
    tmp_path: Path,
) -> None:
    singer_file = tmp_path / "bad-gmail.jsonl"
    singer_file.write_text(
        '{"type":"RECORD","stream":"messages","record":{"id":"msg-bad"}}',
        encoding="utf-8",
    )

    with pytest.raises(
        ConnectorPayloadError,
        match="Gmail record gmail:messages:msg-bad requires body, text, or snippet",
    ):
        load_gmail_source_records(singer_file)


def test_gmail_raw_record_uses_current_permissions_only_when_present() -> None:
    record = gmail_source_record_from_raw(
        {
            "id": "gmail-msg-2",
            "thread_id": "thread-2",
            "subject": "Finance pilot",
            "body": "finance body",
            "source_url": "https://mail.google.com/mail/u/0/#inbox/gmail-msg-2",
            "permission_refs": ["group:finance"],
            "permission_snapshot_status": "current",
        }
    )

    assert record.permission_refs == ("group:finance",)
    assert record.permission_snapshot_status == "current"
    assert record.effective_lifecycle_state == "active"
    assert record.source_url.endswith("#inbox/gmail-msg-2")


def test_gmail_raw_record_maps_trash_label_to_deleted() -> None:
    record = gmail_source_record_from_raw(
        {
            "id": "gmail-msg-trash",
            "threadId": "thread-trash",
            "body": "trash body",
            "labelIds": ["TRASH"],
        }
    )

    assert record.lifecycle_state == "deleted"
    assert record.effective_lifecycle_state == "deleted"


def test_gmail_raw_record_requires_id_and_body() -> None:
    with pytest.raises(ValueError, match="requires id"):
        gmail_source_record_from_raw({"body": "body only"})

    with pytest.raises(ValueError, match="requires body"):
        gmail_source_record_from_raw({"id": "gmail-msg-empty"})


def test_gmail_singer_records_can_be_loaded_from_raw_tap_output(tmp_path: Path) -> None:
    singer_file = tmp_path / "gmail-output.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"messages","record":'
            "{"
            '"id":"gmail-msg-3",'
            '"threadId":"thread-3",'
            '"internalDate":"1716998096000",'
            '"userId":"me",'
            '"snippet":"snippet fallback",'
            '"payload":{'
            '"headers":['
            '{"name":"Subject","value":"Pilot subject"},'
            '{"name":"From","value":"Sender Name <Sender@Example.com>"},'
            '{"name":"To","value":"Ops@example.com"}'
            "],"
            '"parts":['
            "{"
            '"mimeType":"text/plain",'
            '"body":{"data":"UGlsb3QgYm9keSB0ZXh0"}'
            "},"
            "{"
            '"filename":"note.txt",'
            '"mimeType":"text/plain",'
            '"body":{"attachmentId":"att-1"}'
            "}"
            "]"
            "}"
            "}}\n"
        ),
        encoding="utf-8",
    )

    records = load_gmail_source_records(singer_file)

    assert len(records) == 1
    assert records[0].source_ref == "gmail:message:gmail-msg-3"
    assert records[0].thread_ref == "gmail:thread:thread-3"
    assert records[0].title == "Pilot subject"
    assert records[0].body == "Pilot body text"
    assert records[0].source_url == "https://mail.google.com/mail/u/me/#all/thread-3/gmail-msg-3"
    assert records[0].identity_refs == (
        "gmail:email:sender@example.com",
        "gmail:email:ops@example.com",
    )
    assert records[0].attachment_refs == ("gmail:message:gmail-msg-3:attachment:att-1",)
    assert records[0].permission_snapshot_status == "missing"
    assert records[0].effective_lifecycle_state == "restricted"


def test_gmail_singer_loaded_message_with_missing_permissions_stays_out_of_search(
    tmp_path: Path,
) -> None:
    singer_file = tmp_path / "gmail-output.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"messages","record":'
            "{"
            '"id":"gmail-msg-4",'
            '"threadId":"thread-4",'
            '"snippet":"governed restriction marker",'
            '"payload":{'
            '"headers":[{"name":"Subject","value":"Restricted Gmail pilot"}],'
            '"parts":['
            "{"
            '"mimeType":"text/plain",'
            '"body":{"data":"Z292ZXJuZWQgcmVzdHJpY3Rpb24gbWFya2Vy"}'
            "}"
            "]"
            "}"
            "}}\n"
        ),
        encoding="utf-8",
    )
    context = GovernedContext(database_url=f"sqlite:///{tmp_path / 'governed.sqlite'}")

    records = load_gmail_source_records(singer_file)
    context.ingest_source_records(records)

    assert context.search_context("governed restriction marker").results == []
    stored = context.source_records()
    assert [_source_record_legacy_fields(row) for row in stored] == [
        {
            "source_ref": "gmail:message:gmail-msg-4",
            "source_system": "gmail",
            "source_id": "gmail-msg-4",
            "record_type": "email",
            "source_url": "https://mail.google.com/mail/u/0/#all/thread-4/gmail-msg-4",
            "thread_ref": "gmail:thread:thread-4",
            "permission_refs": "[]",
            "permission_snapshot_status": "missing",
            "attachment_refs": "[]",
            "identity_refs": "[]",
            "lifecycle_state": "restricted",
        }
    ]
    assert stored[0]["title"] == "Restricted Gmail pilot"
    assert stored[0]["retrieval_text"] == "governed restriction marker"
    assert context.source_lifecycle() == [
        {
            "source_ref": "gmail:message:gmail-msg-4",
            "state": "restricted",
            "reason": "permission_snapshot_missing",
        }
    ]


def test_gmail_flat_singer_records_keep_current_permissions_behavior(tmp_path: Path) -> None:
    singer_file = tmp_path / "gmail-flat-output.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"messages","record":'
            '{"id":"gmail-msg-5","body":"flat gmail body",'
            '"permission_refs":["group:finance"],'
            '"permission_snapshot_status":"current"}}\n'
        ),
        encoding="utf-8",
    )

    record = load_gmail_source_records(singer_file)[0]

    assert record.source_ref == "gmail:messages:gmail-msg-5"
    assert record.permission_refs == ("group:finance",)
    assert record.permission_snapshot_status == "current"
    assert record.effective_lifecycle_state == "active"


def test_fixture_tap_outputs_configured_singer_file(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture.jsonl"
    fixture.write_text(
        '{"type":"RECORD","stream":"email_messages","record":{"id":"msg-1","body":"body"}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TAP_FOUROK_FIXTURE_FIXTURE_PATH", str(fixture))

    fixture_tap_main()

    assert capsys.readouterr().out == fixture.read_text(encoding="utf-8")


def test_fixture_tap_accepts_slack_namespace_config(
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.delenv("TAP_FOUROK_FIXTURE_FIXTURE_PATH", raising=False)
    monkeypatch.setenv("TAP_FOUROK_SLACK_FIXTURE_FIXTURE_PATH", str(SINGER_SLACK_MESSAGES))

    fixture_tap_main()

    assert '"stream":"slack_messages"' in capsys.readouterr().out


def test_raw_jsonl_target_lands_stdin_records(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    landing_dir = tmp_path / "landing"
    monkeypatch.setenv("TARGET_FOUROK_RAW_JSONL_LANDING_DIR", str(landing_dir))
    monkeypatch.setattr(
        "sys.stdin",
        [
            '{"type":"SCHEMA","stream":"email_messages","schema":{}}\n',
            ('{"type":"RECORD","stream":"email_messages","record":{"id":"msg-1","body":"body"}}\n'),
            '{"type":"STATE","value":{"bookmark":"msg-1"}}\n',
        ],
    )

    raw_jsonl_target_main()

    assert (landing_dir / "email_messages.jsonl").read_text(encoding="utf-8") == (
        '{"body": "body", "id": "msg-1"}\n'
    )
    assert (landing_dir / "state.json").read_text(encoding="utf-8") == ('{"bookmark": "msg-1"}\n')
    stderr = capsys.readouterr().err
    assert '"record_count": 1' in stderr
    assert f'"state_path": "{landing_dir / "state.json"}"' in stderr


def test_committed_meltano_config_wires_fixture_tap_to_raw_target() -> None:
    config = (Path(__file__).parents[3] / "meltano.yml").read_text(encoding="utf-8")

    assert "tap-fourok-fixture" in config
    assert "tap-fourok-slack-fixture" in config
    assert "target-fourok-raw-jsonl" in config
    assert "fixtures/connectors/singer_email_messages.jsonl" in config
    assert "fixtures/connectors/singer_slack_messages.jsonl" in config
    assert ".local/raw/singer" in config
    assert "tap-fourok-fixture target-fourok-raw-jsonl" in config
    assert "tap-fourok-slack-fixture target-fourok-raw-jsonl" in config


def test_source_record_lifecycle_deletion_removes_connector_record_from_search(
    tmp_path: Path,
) -> None:
    singer_file = tmp_path / "deleted-record.jsonl"
    singer_file.write_text(
        "\n".join(
            [
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-004","subject":"Delete me","body":"delete marker searchable"}}'
                ),
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-004","subject":"Delete me","body":"delete marker searchable",'
                    '"lifecycle_state":"deleted"}}'
                ),
            ]
        ),
        encoding="utf-8",
    )
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")

    records = load_singer_source_records(singer_file)
    context.ingest_source_records([records[0]])
    assert context.search_context("delete marker").results
    assert "singer:email_messages:msg-004" in context.raw_source_refs()

    context.ingest_source_records([records[1]])

    assert context.search_context("delete marker").results == []
    assert "singer:email_messages:msg-004" not in context.raw_source_refs()
    assert context.source_lifecycle() == [
        {
            "source_ref": "singer:email_messages:msg-004",
            "state": "deleted",
            "reason": "source_record_lifecycle",
        }
    ]


def test_source_record_lifecycle_deletion_does_not_clear_other_records(
    tmp_path: Path,
) -> None:
    singer_file = tmp_path / "two-records.jsonl"
    singer_file.write_text(
        "\n".join(
            [
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-005","subject":"Keep me","body":"keep marker searchable"}}'
                ),
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-006","subject":"Delete me","body":"removezz searchable"}}'
                ),
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-006","subject":"Delete me","body":"removezz searchable",'
                    '"lifecycle_state":"deleted"}}'
                ),
            ]
        ),
        encoding="utf-8",
    )
    context = GovernedContext()
    records = load_singer_source_records(singer_file)

    context.ingest_source_records(records[:2])
    context.ingest_source_records([records[2]])

    assert context.search_context("keep marker").results
    assert context.search_context("removezz").results == []


def test_source_record_missing_permission_snapshot_restricts_retrieval() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="singer:email_messages:missing-acl",
                source_system="gmail",
                source_id="missing-acl",
                record_type="email",
                title="Unknown permissions",
                body="missingpermissionmarker refund",
                permission_snapshot_status="missing",
            )
        ]
    )

    assert context.search_context("missingpermissionmarker").results == []
    assert context.source_records()[0]["permission_snapshot_status"] == "missing"
    assert context.source_records()[0]["lifecycle_state"] == "restricted"
    assert context.source_lifecycle() == [
        {
            "source_ref": "singer:email_messages:missing-acl",
            "state": "restricted",
            "reason": "permission_snapshot_missing",
        }
    ]


def test_source_record_permission_snapshot_restriction_restores_when_permissions_arrive() -> None:
    context = GovernedContext()
    source_ref = "singer:email_messages:acl-restored"
    restricted = SourceRecord(
        source_ref=source_ref,
        source_system="gmail",
        source_id="acl-restored",
        record_type="email",
        title="Restored permissions",
        body="restoredpermissionmarker refund",
        permission_snapshot_status="missing",
    )
    restored = SourceRecord(
        source_ref=source_ref,
        source_system="gmail",
        source_id="acl-restored",
        record_type="email",
        title="Restored permissions",
        body="restoredpermissionmarker refund",
        permission_refs=("operator",),
        permission_snapshot_status="current",
    )

    context.ingest_source_records([restricted])
    assert context.search_context("restoredpermissionmarker").results == []

    context.ingest_source_records([restored])

    assert context.source_lifecycle() == []
    assert context.source_records()[0]["lifecycle_state"] == "active"
    assert [
        result.source_ref for result in context.search_context("restoredpermissionmarker").results
    ] == [source_ref]


def test_singer_permission_snapshot_status_is_adapted_from_record(tmp_path: Path) -> None:
    singer_file = tmp_path / "missing-acl.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"email_messages","record":'
            '{"id":"msg-missing-acl","subject":"Unknown permissions",'
            '"body":"missing acl marker",'
            '"permission_snapshot_status":"missing"}}\n'
        ),
        encoding="utf-8",
    )

    record = load_singer_source_records(singer_file)[0]

    assert record.permission_snapshot_status == "missing"
    assert record.effective_lifecycle_state == "restricted"
    assert record.lifecycle_reason == "permission_snapshot_missing"


def test_source_record_incremental_update_replaces_only_touched_record(
    tmp_path: Path,
) -> None:
    singer_file = tmp_path / "incremental-records.jsonl"
    singer_file.write_text(
        "\n".join(
            [
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-007","subject":"Keep me","body":"stablealpha searchable"}}'
                ),
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-008","subject":"Update me","body":"oldbeta searchable"}}'
                ),
                (
                    '{"type":"RECORD","stream":"email_messages","record":'
                    '{"id":"msg-008","subject":"Update me","body":"newgamma searchable"}}'
                ),
            ]
        ),
        encoding="utf-8",
    )
    context = GovernedContext()
    records = load_singer_source_records(singer_file)

    context.ingest_source_records(records[:2])
    vector_index = context.build_vector_index()
    context.ingest_source_records([records[2]])

    assert context.search_context("stablealpha").results
    assert context.search_context("oldbeta").results == []
    assert [result.source_ref for result in context.search_context("newgamma").results] == [
        "singer:email_messages:msg-008"
    ]
    assert [result.source_ref for result in vector_index.search("newgamma", limit=1)] == [
        "singer:email_messages:msg-008"
    ]


def test_source_record_permission_refs_filter_search_before_results() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="singer:email_messages:finance-secret",
                source_system="gmail",
                source_id="finance-secret",
                record_type="email",
                title="Finance only",
                body="permissionmarker finance refund",
                permission_refs=("group:finance",),
            ),
            SourceRecord(
                source_ref="singer:email_messages:support-secret",
                source_system="gmail",
                source_id="support-secret",
                record_type="email",
                title="Support only",
                body="permissionmarker support refund",
                permission_refs=("group:support",),
            ),
            SourceRecord(
                source_ref="singer:email_messages:public",
                source_system="gmail",
                source_id="public",
                record_type="email",
                title="Public",
                body="permissionmarker public refund",
            ),
        ]
    )

    finance_response = context.search_context(
        "permissionmarker refund",
        principal=PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
        limit=5,
    )
    support_response = context.search_context(
        "permissionmarker refund",
        principal=PrincipalContext(
            human_id="human:support-1",
            agent_id="agent:context-helper",
            roles=("support",),
        ),
        limit=5,
    )

    assert {result.source_ref for result in finance_response.results} == {
        "singer:email_messages:finance-secret",
        "singer:email_messages:public",
    }
    assert {result.source_ref for result in support_response.results} == {
        "singer:email_messages:support-secret",
        "singer:email_messages:public",
    }
    finance_audit_events = [
        event
        for event in context.audit_events(human_id="human:finance-1")
        if event["event_type"] in {"search", "source_access"}
    ]
    assert [event["event_type"] for event in finance_audit_events] == [
        "search",
        "source_access",
    ]
    assert all(
        "singer:email_messages:support-secret" not in event["source_refs"]
        for event in finance_audit_events
    )
