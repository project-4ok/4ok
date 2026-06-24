import json
from pathlib import Path

from fourok.cli import main
from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"
CONNECTOR_FIXTURES = Path(__file__).parent.parent / "fixtures" / "connectors"
CONTEXT_FIXTURES = Path(__file__).parent.parent / "fixtures" / "context_substrate"


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


def test_cli_dashboard_uses_configured_raw_store(capsys, monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        "\n".join(
            [
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{raw_store}"',
            ]
        ),
        encoding="utf-8",
    )
    context = GovernedContext(state_path, raw_store_path=raw_store)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="gmail:messages:msg-1",
                source_system="gmail",
                source_id="msg-1",
                record_type="email",
                title="Raw storage proof",
                body="Raw storage proof body.",
            )
        ]
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "dashboard",
            "--state",
            str(state_path),
            "--config",
            str(config_path),
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["raw_sources"] == {
        "configured": True,
        "path": str(raw_store),
        "stored_count": 1,
        "source_record_ref_count": 1,
        "source_record_refs": ["gmail:messages:msg-1"],
        "unreferenced_count": 0,
    }


def test_cli_webhook_process_accepts_retry_controls(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    event_file = tmp_path / "invalid-webhook-event.json"
    event_file.write_text(
        json.dumps(
            {
                "event_id": "evt-cli-invalid",
                "source_system": "linear",
                "source_object_id": "OPS-BAD",
                "event_type": "issue.updated",
                "operation": "upsert",
                "payload": {
                    "source_record": {
                        "source_system": "linear",
                        "source_id": "OPS-BAD",
                        "record_type": "work_item",
                        "title": "Invalid webhook issue",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-enqueue",
            str(event_file),
            "--state",
            str(state_path),
            "--raw-store",
            str(raw_store),
        ],
    )
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-process",
            "--state",
            str(state_path),
            "--raw-store",
            str(raw_store),
            "--max-attempts",
            "1",
            "--retry-delay-seconds",
            "120",
        ],
    )
    main()
    processed = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-events",
            "--state",
            str(state_path),
            "--status",
            "invalid",
        ],
    )
    main()
    listed = json.loads(capsys.readouterr().out)

    assert processed == {"claimed": 1, "failed": 0, "invalid": 1, "succeeded": 0}
    assert listed["events"][0]["event_id"] == "evt-cli-invalid"
    assert listed["events"][0]["status"] == "invalid"
    assert listed["events"][0]["attempt_count"] == 1
    assert listed["events"][0]["next_retry_at"] == ""
    assert listed["events"][0]["error_class"] == "WebhookPayloadError"
    assert "source_ref" in listed["events"][0]["error"]


def test_cli_webhook_process_uses_configured_processing_controls(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    captured = {}

    def fake_process_pending_webhook_events(state, context, **kwargs):
        captured["state"] = state
        captured["context"] = context
        captured["kwargs"] = kwargs
        return {"claimed": 0, "failed": 0, "invalid": 0, "succeeded": 0}

    monkeypatch.setattr(
        "fourok.runtime.webhooks_cli.process_pending_webhook_events",
        fake_process_pending_webhook_events,
    )
    config_path.write_text(
        "\n".join(
            [
                "[webhooks]",
                "process_limit = 1",
                "max_attempts = 1",
                "retry_delay_seconds = 120",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-process",
            "--state",
            str(state_path),
            "--config",
            str(config_path),
        ],
    )
    main()
    processed = json.loads(capsys.readouterr().out)

    assert processed == {"claimed": 0, "failed": 0, "invalid": 0, "succeeded": 0}
    assert captured["kwargs"] == {
        "limit": 1,
        "max_attempts": 1,
        "retry_delay_seconds": 120,
    }


def test_cli_webhook_process_flags_override_configured_processing_controls(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    captured = {}

    def fake_process_pending_webhook_events(state, context, **kwargs):
        captured["kwargs"] = kwargs
        return {"claimed": 0, "failed": 0, "invalid": 0, "succeeded": 0}

    monkeypatch.setattr(
        "fourok.runtime.webhooks_cli.process_pending_webhook_events",
        fake_process_pending_webhook_events,
    )
    config_path.write_text(
        "\n".join(
            [
                "[webhooks]",
                "process_limit = 1",
                "max_attempts = 1",
                "retry_delay_seconds = 120",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-process",
            "--state",
            str(state_path),
            "--config",
            str(config_path),
            "--limit",
            "2",
            "--max-attempts",
            "3",
            "--retry-delay-seconds",
            "240",
        ],
    )
    main()
    processed = json.loads(capsys.readouterr().out)

    assert processed == {"claimed": 0, "failed": 0, "invalid": 0, "succeeded": 0}
    assert captured["kwargs"] == {
        "limit": 2,
        "max_attempts": 3,
        "retry_delay_seconds": 240,
    }


def test_cli_webhook_lifecycle_event_without_source_ref_is_invalid(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    event_file = tmp_path / "invalid-lifecycle-webhook-event.json"
    event_file.write_text(
        json.dumps(
            {
                "event_id": "evt-cli-missing-lifecycle-ref",
                "source_system": "linear",
                "source_object_id": "OPS-MISSING",
                "event_type": "issue.deleted",
                "operation": "delete",
                "payload": {"reason": "source_deleted"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-enqueue",
            str(event_file),
            "--state",
            str(state_path),
        ],
    )
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-process",
            "--state",
            str(state_path),
        ],
    )
    main()
    processed = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-events",
            "--state",
            str(state_path),
            "--status",
            "invalid",
        ],
    )
    main()
    listed = json.loads(capsys.readouterr().out)

    assert processed == {"claimed": 1, "failed": 0, "invalid": 1, "succeeded": 0}
    assert listed["events"][0]["event_id"] == "evt-cli-missing-lifecycle-ref"
    assert listed["events"][0]["error_class"] == "WebhookPayloadError"
    assert "source_ref" in listed["events"][0]["error"]


def test_cli_ingests_text_layer_pdf_source_record(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    pdf_file = tmp_path / "contract.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    def fake_pdf_source_record(*args, **kwargs):
        assert args == (pdf_file,)
        assert kwargs["landing_dir"] == tmp_path / "raw-pdf"
        return SourceRecord(
            source_ref="pdf:document:contract",
            source_system="pdf",
            source_id="contract",
            record_type="document",
            title="contract.pdf",
            body="PDF contract searchable marker.",
            checksum="sha256:abc",
            version="sha256:abc",
            raw_ref=(tmp_path / "raw-pdf" / "abc.pdf").as_posix(),
            metadata={"ocr_used": False},
        )

    monkeypatch.setattr(
        "fourok.cli_parts.commands_imports.pdf_source_record", fake_pdf_source_record
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "ingest-pdf",
            str(pdf_file),
            "--state",
            str(state_path),
            "--landing-dir",
            str(tmp_path / "raw-pdf"),
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    context = GovernedContext(state_path)
    assert output == {
        "checksum": "sha256:abc",
        "input": str(pdf_file),
        "ocr_used": False,
        "raw_ref": (tmp_path / "raw-pdf" / "abc.pdf").as_posix(),
        "record_type": "document",
        "source_id": "contract",
        "source_ref": "pdf:document:contract",
        "text_length": 31,
    }
    assert [
        result.source_ref for result in context.search_context("contract searchable").results
    ] == ["pdf:document:contract"]
