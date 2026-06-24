from pathlib import Path

import pytest

from gcb.etl.extract.connectors import land_singer_records, load_slack_source_records
from gcb.etl.extract.slack_adapter import (
    load_slack_landed_source_records,
    slack_channel_source_record_from_raw,
    slack_message_source_record_from_raw,
    slack_user_source_record_from_raw,
)
from gcb.governance import GovernedContext


def test_slack_live_tap_streams_feed_source_record_adapter() -> None:
    landing_dir = Path(".local/test-artifacts/connectors/slack-live-streams")
    if landing_dir.exists():
        for path in landing_dir.glob("*"):
            path.unlink()
    singer_file = landing_dir / "slack-live-sample.jsonl"
    landing_dir.mkdir(parents=True, exist_ok=True)
    singer_file.write_text(
        "\n".join(
            [
                '{"type":"SCHEMA","stream":"channels","schema":{}}',
                (
                    '{"type":"RECORD","stream":"channels","record":'
                    '{"id":"C1","name":"ops","is_archived":false,"created":1717236000,'
                    '"num_members":3,"topic":{"value":"Ops coordination"},'
                    '"purpose":{"value":"Customer operations"}}}'
                ),
                '{"type":"SCHEMA","stream":"users","schema":{}}',
                (
                    '{"type":"RECORD","stream":"users","record":'
                    '{"id":"U1","name":"olivia","real_name":"Olivia Example",'
                    '"team_id":"T1","profile":{"email":"olivia@example.com"}}}'
                ),
                '{"type":"SCHEMA","stream":"messages","schema":{}}',
                (
                    '{"type":"RECORD","stream":"messages","record":'
                    '{"channel_id":"C1","ts":"1717236300.000000","text":"Status updated",'
                    '"thread_ts":"1717236200.000000","user":"U1",'
                    '"permalink":"https://example.slack.com/archives/C1/p1717236300000000"}}'
                ),
                '{"type":"STATE","value":{"bookmarks":{"messages":{"ts":"1717236300.000000"}}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = land_singer_records(singer_file, landing_dir)
    records = load_slack_landed_source_records(landing_dir)

    assert report.streams == {"channels": 1, "messages": 1, "users": 1}
    assert [record.source_ref for record in records] == [
        "slack:channel:C1",
        "slack:message:C1:1717236300.000000",
        "slack:user:U1",
    ]
    assert [record.record_type for record in records] == ["work_item", "message", "person"]
    assert records[0].body == "ops Ops coordination Customer operations"
    assert records[1].thread_ref == "slack:thread:C1:1717236200.000000"
    assert records[2].identity_refs == ("slack:user:U1", "slack:email:olivia@example.com")


def test_slack_fixture_stream_remains_supported() -> None:
    source_records = load_slack_source_records(
        Path("fixtures/connectors/singer_slack_messages.jsonl")
    )

    assert [record.source_ref for record in source_records] == [
        "slack:message:C123456:1717236000.000000",
        "slack:message:C123456:1717236300.000000",
    ]


def test_landed_slack_messages_and_threads_import_as_retrieval_records(tmp_path: Path) -> None:
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir()
    (landing_dir / "messages.jsonl").write_text(
        (
            '{"channel_id":"C1","ts":"1717236300.000000","text":"Alpha launch risk",'
            '"thread_ts":"1717236300.000000","user":"U1",'
            '"permalink":"https://example.slack.com/archives/C1/p1717236300000000"}\n'
        ),
        encoding="utf-8",
    )
    (landing_dir / "threads.jsonl").write_text(
        (
            '{"channel_id":"C1","thread_ts":"1717236300.000000",'
            '"ts":"1717236360.000000","text":"Beta mitigation shipped","user":"U2"}\n'
        ),
        encoding="utf-8",
    )

    source_records = load_slack_landed_source_records(landing_dir)
    context = GovernedContext(tmp_path / "state.sqlite")
    context.ingest_source_records(source_records)

    stored_messages = [
        record for record in context.source_records() if record["record_type"] == "message"
    ]
    retrieval_units = context.retrieval_units()

    assert [record["source_ref"] for record in stored_messages] == [
        "slack:message:C1:1717236300.000000",
        "slack:message:C1:1717236360.000000",
    ]
    assert {record["permission_refs"] for record in stored_messages} == {'["slack:channel:C1"]'}
    assert [record["raw_ref"] for record in stored_messages] == [
        "slack:raw:messages:C1:1717236300.000000",
        "slack:raw:threads:C1:1717236360.000000",
    ]
    assert {
        unit["source_ref"] for unit in retrieval_units if unit["source_ref"].startswith("slack:")
    } == {
        "slack:message:C1:1717236300.000000",
        "slack:message:C1:1717236360.000000",
    }
    assert any("Alpha launch risk" in unit["prepared_text"] for unit in retrieval_units)
    assert any("Beta mitigation shipped" in unit["prepared_text"] for unit in retrieval_units)


def test_slack_message_adapter_preserves_textless_live_messages_as_metadata_records() -> None:
    record = slack_message_source_record_from_raw(
        {
            "channel_id": "C1",
            "ts": "1717236500.000000",
            "subtype": "channel_join",
            "user": "U1",
        }
    )

    assert record.source_ref == "slack:message:C1:1717236500.000000"
    assert record.body == "Slack message without text channel_join U1"
    assert record.metadata["text_missing"] == "true"
    assert record.metadata["subtype"] == "channel_join"


def test_slack_user_adapter_requires_id() -> None:
    with pytest.raises(ValueError, match="Slack user record requires id"):
        slack_user_source_record_from_raw({"name": "missing"})


def test_slack_channel_adapter_requires_id() -> None:
    with pytest.raises(ValueError, match="Slack channel record requires id"):
        slack_channel_source_record_from_raw({"name": "missing"})


def test_slack_message_adapter_rejects_malformed_payload() -> None:
    with pytest.raises(
        ValueError,
        match="Slack message record requires channel_id and ts",
    ):
        slack_message_source_record_from_raw({"text": "missing ids"})
