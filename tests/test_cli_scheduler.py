import json
import shutil
from datetime import datetime
from pathlib import Path

from fourok.cli import main
from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.extract.sync_jobs import (
    complete_connector_job,
    connector_job_runs,
    fail_connector_job,
    start_connector_job,
)
from fourok.etl.load.retrieval_records import retrieval_record_rows
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"
CONNECTOR_FIXTURES = Path(__file__).parent.parent / "fixtures" / "connectors"
CONTEXT_FIXTURES = Path(__file__).parent.parent / "fixtures" / "context_substrate"
LOCAL_TEST_ARTIFACTS = Path(".local/test-artifacts")


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


def test_cli_run_imports_retry_failed_waits_for_backoff(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="context-fixture",
        job_id="failed-job",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=job.job_id,
        error="source unavailable",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
            "--retry-failed",
            "--retry-base-delay-seconds",
            "300",
            "--now",
            "2026-06-01T10:01:00+00:00",
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "retry_not_due",
        "connector_name": "context-fixture",
        "attempt": 2,
        "earliest_retry_at": "2026-06-01T10:05:00+00:00",
    }


def test_cli_run_imports_retry_failed_uses_configured_scheduler_backoff(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        "[scheduler]\nretry_delay_seconds = 120\nmax_attempts = 3\n",
        encoding="utf-8",
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="context-fixture",
        job_id="failed-job",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=job.job_id,
        error="source unavailable",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
            "--config",
            str(config_path),
            "--retry-failed",
            "--now",
            "2026-06-01T10:01:00+00:00",
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "retry_not_due",
        "connector_name": "context-fixture",
        "attempt": 2,
        "earliest_retry_at": "2026-06-01T10:02:00+00:00",
    }


def test_cli_run_imports_retry_failed_respects_configured_max_attempts(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        "[scheduler]\nretry_delay_seconds = 120\nmax_attempts = 1\n",
        encoding="utf-8",
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="context-fixture",
        job_id="failed-job",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=job.job_id,
        error="source unavailable",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
            "--config",
            str(config_path),
            "--retry-failed",
            "--now",
            "2026-06-01T10:05:00+00:00",
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "skipped",
        "connector_name": "context-fixture",
        "reason": "connector_retry_attempts_exhausted",
        "max_attempts": 1,
    }


def test_cli_run_imports_marks_malformed_connector_payload_invalid(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    singer_file = tmp_path / "bad-gmail.jsonl"
    singer_file.write_text(
        json.dumps(
            {
                "type": "RECORD",
                "stream": "messages",
                "record": {"id": "msg-bad", "threadId": "thread-bad"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "gmail-singer",
            "--singer-file",
            str(singer_file),
            "--state",
            str(state_path),
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == "Gmail record gmail:messages:msg-bad requires body, text, or snippet"
    else:
        raise AssertionError("malformed connector payload should stop the run")

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    jobs = connector_job_runs(state.engine, state.connector_job_runs)

    assert jobs[0]["status"] == "invalid"
    assert jobs[0]["connector_name"] == "gmail-singer"
    assert jobs[0]["raw_output_ref"] == str(singer_file)
    assert jobs[0]["error"] == (
        "Gmail record gmail:messages:msg-bad requires body, text, or snippet"
    )
    assert GovernedContext(state_path).source_records() == []


def test_cli_run_imports_context_fixture_repeated_runs_are_upsert_safe(capsys, monkeypatch) -> None:
    artifact_dir = LOCAL_TEST_ARTIFACTS / "run-imports-context-fixture-upsert"
    shutil.rmtree(artifact_dir, ignore_errors=True)
    artifact_dir.mkdir(parents=True)
    state_path = artifact_dir / "state.sqlite"
    fixture_path = CONTEXT_FIXTURES / "source_snapshot_eval.json"

    def run_once(now: str) -> dict[str, object]:
        monkeypatch.setattr(
            "sys.argv",
            [
                "fourok",
                "run-imports",
                "--connector",
                "context-fixture",
                "--fixture",
                str(fixture_path),
                "--state",
                str(state_path),
                "--now",
                now,
            ],
        )
        main()
        return json.loads(capsys.readouterr().out)

    first = run_once("2026-06-01T10:00:00+00:00")
    context_after_first = GovernedContext(state_path)
    first_source_refs = {row["source_ref"] for row in context_after_first.source_records()}
    first_retrieval_units = len(context_after_first.retrieval_units())

    second = run_once("2026-06-01T10:01:00+00:00")
    context_after_second = GovernedContext(state_path)
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    jobs = sorted(
        connector_job_runs(state.engine, state.connector_job_runs),
        key=lambda job: str(job["started_at"]),
    )

    assert first["status"] == "succeeded"
    assert first["import_counts"] == {
        "new_count": 20,
        "unchanged_count": 0,
        "changed_count": 0,
        "deleted_count": 0,
    }
    assert second["status"] == "succeeded"
    assert second["import_counts"] == {
        "new_count": 0,
        "unchanged_count": 20,
        "changed_count": 0,
        "deleted_count": 0,
    }
    assert {row["source_ref"] for row in context_after_second.source_records()} == first_source_refs
    assert len(context_after_second.retrieval_units()) == first_retrieval_units
    assert [job["status"] for job in jobs] == ["succeeded", "succeeded"]
    assert jobs[0]["output_state"]["source_ref_count"] == 20
    assert jobs[1]["output_state"]["unchanged_count"] == 20


def test_cli_run_imports_emits_safe_runtime_span(capsys, monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retrieval]\nmax_words = 6\noverlap_words = 2\n", encoding="utf-8")
    spans: list[dict[str, object]] = []

    class FakeSpan:
        def __init__(self, name: str) -> None:
            self.name = name
            self.attributes: dict[str, object] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            spans.append({"name": self.name, "attributes": self.attributes})

        def set_attribute(self, key: str, value: object) -> None:
            self.attributes[key] = value

    class FakeTracer:
        def start_as_current_span(self, name: str) -> FakeSpan:
            return FakeSpan(name)

    monkeypatch.setattr("fourok.cli_parts.import_helpers.trace.get_tracer", lambda _name: FakeTracer())
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
            "--config",
            str(config_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert spans == [
        {
            "name": "fourok.retrieval.prepare",
            "attributes": {
                "fourok.source_record.count": 20,
                "fourok.retrieval.unit_count": 53,
                "fourok.retrieval.max_words": 6,
                "fourok.retrieval.overlap_words": 2,
            },
        },
        {
            "name": "fourok.run_imports",
            "attributes": {
                "fourok.connector.name": "context-fixture",
                "fourok.connector.attempt": 1,
                "fourok.import.status": "succeeded",
                "fourok.import.record_count": 20,
                "fourok.import.deleted_record_count": 0,
                "fourok.import.restricted_count": 0,
            },
        },
    ]
    assert "ask Robin" not in str(spans)
    assert str(CONTEXT_FIXTURES) not in str(spans)


def test_cli_dashboard_prints_operator_stats(capsys, monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Dashboard customer issue",
                body="Dashboard customer issue.",
            )
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="linear",
        job_id="job-1",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name="linear",
        output_state={"cursor": "1"},
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "dashboard",
            "--state",
            str(state_path),
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["source_records"]["total"] == 1
    assert output["source_records"]["by_record_type"] == {"work_item": 1}
    assert output["canonical_objects"]["by_object_type"] == {"WorkItem": 1}
    assert output["entity_links"]["link_coverage"] == 0.0
    assert output["connectors"]["state_count"] == 1
    assert output["connectors"]["jobs"]["by_status"] == {"succeeded": 1}
    assert output["audit"]["total_events"] == 0
    assert output["alerts"] == {"status": "ok", "items": []}


def test_cli_dashboard_uses_configured_scheduler_retry_visibility(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        "[scheduler]\nretry_delay_seconds = 120\nmax_attempts = 3\n",
        encoding="utf-8",
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail",
        job_id="failed-job",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=job.job_id,
        error="source unavailable",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
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
    jobs = output["connectors"]["jobs"]
    assert jobs["latest_failed_connector"] == "gmail"
    assert jobs["next_retry_attempt"] == 2
    assert jobs["earliest_retry_at"] == "2026-06-01T10:02:00+00:00"
    assert jobs["retry_exhausted"] is False


def test_cli_rebuilds_retrieval_units_from_source_records(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    config = tmp_path / "fourok.toml"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="docs:runbook:rebuild",
                source_system="docs",
                source_id="rebuild",
                record_type="document",
                title="Rebuild runbook",
                body=(
                    "one two three four five six seven eight nine ten eleven "
                    "twelve thirteen fourteen"
                ),
            )
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    initial_rows = retrieval_record_rows(state.engine, state.retrieval_records)
    assert len(initial_rows) == 1
    config.write_text("[retrieval]\nmax_words = 6\noverlap_words = 2\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "rebuild-retrieval-units",
            "--state",
            str(state_path),
            "--config",
            str(config),
            "--confirm-rebuild",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    rows = retrieval_record_rows(state.engine, state.retrieval_records)
    assert output == {
        "status": "completed",
        "source_records": 1,
        "retrieval_units_deleted": 1,
        "retrieval_units_created": len(rows),
    }
    assert len(rows) > 1
    assert context.source_records()[0]["source_ref"] == "docs:runbook:rebuild"
    assert all(row["source_ref"] == "docs:runbook:rebuild" for row in rows)


def test_cli_rebuild_retrieval_units_requires_confirmation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "rebuild-retrieval-units",
            "--state",
            str(tmp_path / "state.sqlite"),
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == "rebuild-retrieval-units requires --confirm-rebuild"
    else:
        raise AssertionError("rebuild should require explicit confirmation")


def test_cli_webhook_backlog_enqueues_processes_and_lists_events(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    event_file = tmp_path / "webhook-event.json"
    event_file.write_text(
        json.dumps(
            {
                "event_id": "evt-cli-1",
                "source_system": "linear",
                "source_object_id": "OPS-CLI",
                "event_type": "issue.updated",
                "operation": "upsert",
                "idempotency_key": "linear:OPS-CLI:1",
                "payload": {
                    "source_record": {
                        "source_ref": "linear:issue:OPS-CLI",
                        "source_system": "linear",
                        "source_id": "OPS-CLI",
                        "record_type": "work_item",
                        "title": "CLI webhook issue",
                        "body": "CLI webhook customer marker.",
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
    enqueued = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "webhook-process",
            "--state",
            str(state_path),
            "--raw-store",
            str(raw_store),
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
            "succeeded",
        ],
    )
    main()
    listed = json.loads(capsys.readouterr().out)
    context = GovernedContext(state_path)

    assert enqueued["status"] == "pending"
    assert enqueued["raw_payload_ref"] == "webhook:linear:evt-cli-1:raw"
    assert processed == {"claimed": 1, "failed": 0, "invalid": 0, "succeeded": 1}
    assert [event["event_id"] for event in listed["events"]] == ["evt-cli-1"]
    assert [result.source_ref for result in context.search_context("CLI webhook").results] == [
        "linear:issue:OPS-CLI"
    ]


def test_cli_webhook_process_uses_configured_retrieval_chunk_policy(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retrieval]\nmax_words = 6\noverlap_words = 2\n", encoding="utf-8")
    event_file = tmp_path / "webhook-event.json"
    event_file.write_text(
        json.dumps(
            {
                "event_id": "evt-cli-chunking",
                "source_system": "google_drive",
                "source_object_id": "configured",
                "event_type": "document.updated",
                "operation": "upsert",
                "payload": {
                    "source_record": {
                        "source_ref": "docs:configured",
                        "source_system": "google_drive",
                        "source_id": "configured",
                        "record_type": "document",
                        "title": "Policy",
                        "body": " ".join(f"word{index}" for index in range(12)),
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
            "--config",
            str(config_path),
        ],
    )
    main()
    processed = json.loads(capsys.readouterr().out)

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    rows = retrieval_record_rows(state.engine, state.retrieval_records)
    assert processed == {"claimed": 1, "failed": 0, "invalid": 0, "succeeded": 1}
    assert [row["unit_index"] for row in rows] == [0, 1, 2]
    assert [row["prepared_text"] for row in rows] == [
        "Policy word0 word1 word2 word3 word4",
        "word3 word4 word5 word6 word7 word8",
        "word7 word8 word9 word10 word11",
    ]
