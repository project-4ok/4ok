import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from fourok.etl.extract.openviking_sessions import write_openviking_session_messages_jsonl
from fourok.etl.extract.sync_jobs import connector_job_runs, start_connector_job
from fourok.governance.state import create_governed_context_state
from fourok.runtime.source_imports import SourceRecordImportReport

_dagster = pytest.importorskip("dagster")

_DEFINITIONS = Path("deploy/dagster/definitions.py")
_SPEC = importlib.util.spec_from_file_location("fourok_dagster_definitions", _DEFINITIONS)
assert _SPEC is not None
assert _SPEC.loader is not None
_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_module)

_CHECK_SCRIPT = Path("scripts/check_dagster_pipeline.py")
_CHECK_SPEC = importlib.util.spec_from_file_location("fourok_dagster_pipeline_check", _CHECK_SCRIPT)
assert _CHECK_SPEC is not None
assert _CHECK_SPEC.loader is not None
_check_module = importlib.util.module_from_spec(_CHECK_SPEC)
_CHECK_SPEC.loader.exec_module(_check_module)

defs = _module.defs
_target_report: Any = _module._target_report
_landed_stream_counts: Any = _module._landed_stream_counts
_count_by: Any = _module._count_by
_checkpoint_keys: Any = _module._checkpoint_keys
_meltano_environment: Any = _module._meltano_environment
_singer_secret_aliases: Any = _module._singer_secret_aliases
_live_connector_asset_names: Any = _check_module._live_connector_asset_names
_load_dotenv_defaults: Any = _check_module._load_dotenv_defaults
_verify_live_db_changed: Any = _check_module._verify_live_db_changed
_record_live_connector_success: Any = _module._record_live_connector_success
_meltano_asset_span_name: Any = _module._meltano_asset_span_name
_source_records_asset_span_name: Any = _module._source_records_asset_span_name


def test_dagster_definitions_expose_only_operator_product_lineage_assets() -> None:
    asset_names = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}

    assert asset_names == {
        "meltano_slack_live_raw_landing",
        "fourok_slack_live_source_records_from_raw_landing",
        "meltano_twenty_live_raw_landing",
        "fourok_twenty_live_source_records_from_raw_landing",
        "meltano_linear_live_raw_landing",
        "fourok_linear_live_source_records_from_raw_landing",
        "meltano_google_drive_live_raw_landing",
        "fourok_google_drive_live_source_records_from_raw_landing",
        "fourok_openviking_live_source_records_from_sessions",
        "fourok_webhook_backlog",
        "fourok_canonical_objects_and_entity_links",
        "fourok_retrieval_records",
        "fourok_operator_dashboard",
        "fourok_audit_metadata",
    }

    obsolete_or_fixture_assets = {
        "meltano_singer_raw_landing",
        "meltano_slack_raw_landing",
        "meltano_twenty_raw_landing",
        "meltano_linear_raw_landing",
        "meltano_google_drive_raw_landing",
        "fourok_source_records_from_raw_landing",
        "fourok_slack_source_records_from_raw_landing",
        "fourok_twenty_source_records_from_raw_landing",
        "fourok_linear_source_records_from_raw_landing",
        "fourok_google_drive_source_records_from_raw_landing",
        "fourok_golden_retrieval_eval",
    }
    assert asset_names.isdisjoint(obsolete_or_fixture_assets)


def test_dagster_entrypoint_keeps_resource_definitions_separate() -> None:
    definitions_source = _DEFINITIONS.read_text(encoding="utf-8")
    resources_source = Path("src/fourok/orchestration/dagster_resources.py").read_text(
        encoding="utf-8"
    )

    assert "class RawLandingResource" not in definitions_source
    assert "class MeltanoProjectResource" not in definitions_source
    assert "class FourokRuntimeResource" not in definitions_source
    assert "def build_default_resources" in resources_source
    assert "ConnectorEnvResource" in resources_source


def test_dagster_trace_span_names_match_operator_lineage_assets() -> None:
    assert _meltano_asset_span_name("slack-live-to-raw") == "meltano_slack_live_raw_landing"
    assert (
        _meltano_asset_span_name("google-drive-live-to-raw")
        == "meltano_google_drive_live_raw_landing"
    )
    assert (
        _source_records_asset_span_name("google_drive-live")
        == "fourok_google_drive_live_source_records_from_raw_landing"
    )
    assert (
        _source_records_asset_span_name("slack-live")
        == "fourok_slack_live_source_records_from_raw_landing"
    )


def test_dagster_definitions_expose_recurring_live_ingestion_hooks() -> None:
    job_names = {job.name for job in defs.resolve_all_job_defs()}
    schedule_names = {schedule.name for schedule in defs.schedules or []}
    sensor_names = {sensor.name for sensor in defs.sensors or []}

    assert "fourok_hourly_live_backfill" in job_names
    assert "fourok_process_webhook_backlog" in job_names
    assert schedule_names == {"fourok_hourly_live_backfill_schedule"}
    assert sensor_names == {"fourok_webhook_backlog_sensor"}
    [backfill_schedule] = defs.schedules or []
    assert backfill_schedule.default_status.name == "RUNNING"


def test_dagster_hourly_live_backfill_rebuilds_retrieval_and_operator_counts() -> None:
    job = defs.resolve_job_def("fourok_hourly_live_backfill")
    node_names = {node.name for node in job.all_node_defs}

    assert "fourok_webhook_backlog" in node_names
    assert "fourok_openviking_live_source_records_from_sessions" in node_names
    assert "fourok_canonical_objects_and_entity_links" in node_names
    assert "fourok_retrieval_records" in node_names
    assert "fourok_operator_dashboard" in node_names
    assert "fourok_audit_metadata" in node_names
    assert "fourok_golden_retrieval_eval" not in node_names
    assert job.executor_def.name == "in_process"
    upstream_node_names = {
        output.node_name
        for outputs in job.dependency_structure.input_to_upstream_outputs_for_node(
            "fourok_retrieval_records"
        ).values()
        for output in outputs
    }
    assert upstream_node_names == {"fourok_webhook_backlog"}


def test_dagster_normalizes_openviking_sessions_for_live_import(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "session-1-topic-123.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "id": "session-1"}),
                json.dumps(
                    {
                        "type": "message",
                        "id": "msg-1",
                        "timestamp": "2026-06-03T08:00:23.292Z",
                        "message": {
                            "role": "user",
                            "senderName": "Simon",
                            "content": "What are my priorities today?",
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    messages = tmp_path / "messages.jsonl"

    count = write_openviking_session_messages_jsonl(sessions, messages)

    assert count == 1
    [row] = [json.loads(line) for line in messages.read_text(encoding="utf-8").splitlines()]
    assert row["conversation_id"] == "session-1-topic-123"
    assert row["message_id"] == "msg-1"
    assert row["message"]["content"] == "What are my priorities today?"
    assert row["permission_refs"] == ["openviking:conversation:session-1-topic-123"]


def test_dagster_hourly_backfill_partial_failure_tolerant() -> None:
    job = defs.resolve_job_def("fourok_hourly_live_backfill")
    webhook_upstream_node_names = {
        output.node_name
        for outputs in job.dependency_structure.input_to_upstream_outputs_for_node(
            "fourok_webhook_backlog"
        ).values()
        for output in outputs
    }
    canonical_upstream_node_names = {
        output.node_name
        for outputs in job.dependency_structure.input_to_upstream_outputs_for_node(
            "fourok_canonical_objects_and_entity_links"
        ).values()
        for output in outputs
    }
    retrieval_upstream_node_names = {
        output.node_name
        for outputs in job.dependency_structure.input_to_upstream_outputs_for_node(
            "fourok_retrieval_records"
        ).values()
        for output in outputs
    }
    assert webhook_upstream_node_names == set()
    assert canonical_upstream_node_names == {"fourok_webhook_backlog"}
    assert retrieval_upstream_node_names == {"fourok_webhook_backlog"}


def test_dagster_live_source_import_records_operator_freshness_and_counts(
    tmp_path: Path,
) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "fourok.sqlite",
        database_url=None,
        raw_store_path=None,
    )
    report = SourceRecordImportReport(
        record_count=3,
        source_refs=("twenty:company:1", "twenty:person:1", "twenty:person:2"),
        source_systems=("twenty",),
        record_types=("Company", "Person"),
        lifecycle_states=("active",),
        restricted_count=0,
        retrieval_unit_count=7,
    )

    _record_live_connector_success(
        state,
        connector_name="twenty-live",
        report=report,
        landing_dir=tmp_path / "twenty_live",
        dagster_run_id="run-123",
    )

    [job] = connector_job_runs(state.engine, state.connector_job_runs)
    assert job["connector_name"] == "twenty-live"
    assert job["status"] == "succeeded"
    assert job["raw_output_ref"] == str(tmp_path / "twenty_live")
    assert job["output_state"] == {
        "freshness_status": "fresh",
        "idempotency_status": "recorded",
        "source_record_count": 3,
        "retrieval_record_count": 7,
        "dagster_run_id": "run-123",
    }


def test_dagster_live_source_import_does_not_duplicate_outer_running_job(
    tmp_path: Path,
) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "fourok.sqlite",
        database_url=None,
        raw_store_path=None,
    )
    start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="google_drive-live",
        job_id="outer-run-live-ingestion",
    )
    report = SourceRecordImportReport(
        record_count=4,
        source_refs=("google_drive:file:1",),
        source_systems=("google_drive",),
        record_types=("Document",),
        lifecycle_states=("active",),
        restricted_count=0,
        retrieval_unit_count=4,
    )

    _record_live_connector_success(
        state,
        connector_name="google_drive-live",
        report=report,
        landing_dir=tmp_path / "google_drive_live",
        dagster_run_id="run-456",
    )

    [job] = connector_job_runs(state.engine, state.connector_job_runs)
    assert job["job_id"] == "outer-run-live-ingestion"
    assert job["connector_name"] == "google_drive-live"
    assert job["status"] == "running"
    assert job["output_state"] == {}
    assert job["raw_output_ref"] == ""


def test_dagster_target_report_uses_latest_json_record_count() -> None:
    stderr = "\n".join(
        [
            "meltano log line",
            '{"record_count": 1, "schema_messages": 1}',
            '{"record_count": 2, "schema_messages": 1, "state_messages": 1}',
        ]
    )

    assert _target_report(stderr) == {
        "record_count": 2,
        "schema_messages": 1,
        "state_messages": 1,
    }


def test_dagster_landed_stream_counts_jsonl_records() -> None:
    landing_dir = Path(".local/test-artifacts/dagster-pipeline/landed-stream-counts")
    shutil.rmtree(landing_dir, ignore_errors=True)
    landing_dir.mkdir(parents=True)

    (landing_dir / "email_messages.jsonl").write_text(
        '{"id": 1}\n{"id": 2}\n',
        encoding="utf-8",
    )
    (landing_dir / "empty.jsonl").write_text("\n", encoding="utf-8")

    assert _landed_stream_counts(landing_dir) == {
        "email_messages": 2,
        "empty": 0,
    }


def test_dagster_checkpoint_keys_reads_latest_landing_state() -> None:
    landing_dir = Path(".local/test-artifacts/dagster-pipeline/checkpoint-keys")
    shutil.rmtree(landing_dir, ignore_errors=True)
    landing_dir.mkdir(parents=True)
    state_path = landing_dir / "state.json"
    state_path.write_text('{"bookmarks": {}, "currently_syncing": "messages"}\n', encoding="utf-8")

    assert _checkpoint_keys(state_path) == ["bookmarks", "currently_syncing"]


def test_dagster_meltano_environment_injects_secrets_without_overriding_landing_dir(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EXISTING_ENV", "kept")

    env = _meltano_environment(
        landing_dir=Path(".local/raw/singer/slack"),
        secret_env={
            "SLACK_BOT_TOKEN": "secret-token",
            "TARGET_FOUROK_RAW_JSONL_LANDING_DIR": "wrong",
        },
    )

    assert env["EXISTING_ENV"] == "kept"
    assert env["SLACK_BOT_TOKEN"] == "secret-token"
    assert env["TARGET_FOUROK_RAW_JSONL_LANDING_DIR"] == ".local/raw/singer/slack"


def test_dagster_meltano_environment_adds_singer_secret_aliases() -> None:
    env = _meltano_environment(
        landing_dir=Path(".local/raw/singer/slack"),
        secret_env={"SLACK_BOT_TOKEN": "secret-token"},
    )

    assert env["SLACK_BOT_TOKEN"] == "secret-token"
    assert env["TAP_SLACK_API_KEY"] == "secret-token"


def test_dagster_meltano_environment_aliases_runtime_slack_bot_token(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "runtime-token")
    monkeypatch.delenv("TAP_SLACK_API_KEY", raising=False)

    env = _meltano_environment(
        landing_dir=Path(".local/raw/singer/slack"),
        secret_env={},
    )

    assert env["TAP_SLACK_API_KEY"] == "runtime-token"


def test_dagster_meltano_environment_defaults_slack_to_readable_channel_types(
    monkeypatch,
) -> None:
    monkeypatch.delenv("TAP_SLACK_CHANNEL_TYPES", raising=False)

    env = _meltano_environment(
        landing_dir=Path(".local/raw/singer/slack"),
        secret_env={"SLACK_BOT_TOKEN": "secret-token"},
    )

    assert env["TAP_SLACK_CHANNEL_TYPES"] == '["im","mpim","private_channel"]'


def test_dagster_meltano_environment_preserves_explicit_slack_channel_types(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TAP_SLACK_CHANNEL_TYPES", '["public_channel"]')

    env = _meltano_environment(
        landing_dir=Path(".local/raw/singer/slack"),
        secret_env={"SLACK_BOT_TOKEN": "secret-token"},
    )

    assert env["TAP_SLACK_CHANNEL_TYPES"] == '["public_channel"]'


def test_dagster_meltano_environment_adds_linear_api_key_alias() -> None:
    env = _meltano_environment(
        landing_dir=Path(".local/raw/singer/linear_live"),
        secret_env={"TAP_LINEAR_API_KEY": "secret-token"},
    )

    assert env["TAP_LINEAR_API_KEY"] == "secret-token"
    assert env["LINEAR_API_KEY"] == "secret-token"


def test_dagster_meltano_environment_does_not_override_explicit_tap_secret() -> None:
    env = _singer_secret_aliases(
        {
            "SLACK_BOT_TOKEN": "source-token",
            "TAP_SLACK_API_KEY": "tap-token",
        }
    )

    assert env["TAP_SLACK_API_KEY"] == "tap-token"


def test_dagster_check_live_db_accepts_idempotent_current_rows(monkeypatch, capsys) -> None:
    snapshots = iter(
        [
            {"source_records": 42, "retrieval_records": 99},
            {"source_records": 42, "retrieval_records": 99},
        ]
    )
    monkeypatch.setattr(_check_module, "_runtime_db_counts", lambda: next(snapshots))

    _verify_live_db_changed(_check_module._runtime_db_counts())

    output = capsys.readouterr().out
    assert "live_db_source_records_delta=0" in output
    assert "live_db_retrieval_records_delta=0" in output
    assert "live_db_current_status=ok" in output


def test_dagster_check_live_db_rejects_decreased_rows(monkeypatch) -> None:
    snapshots = iter(
        [
            {"source_records": 42, "retrieval_records": 99},
            {"source_records": 41, "retrieval_records": 99},
        ]
    )
    monkeypatch.setattr(_check_module, "_runtime_db_counts", lambda: next(snapshots))

    with pytest.raises(SystemExit, match="decreased runtime DB rows"):
        _verify_live_db_changed(_check_module._runtime_db_counts())


def test_dagster_live_connector_asset_names_can_select_linear_only() -> None:
    assert _live_connector_asset_names("linear") == {
        "meltano_linear_live_raw_landing",
        "fourok_linear_live_source_records_from_raw_landing",
    }


def test_dagster_check_loads_project_dotenv_defaults(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "LINEAR_API_KEY=project-123\nSLACK_BOT_TOKEN=dotenv-value\n",
        encoding="utf-8",
    )

    _load_dotenv_defaults(dotenv)

    assert _check_module.os.environ["LINEAR_API_KEY"] == "project-123"


def test_dagster_count_by_returns_stable_counts() -> None:
    assert _count_by(
        [
            {"object_type": "person"},
            {"object_type": "organization"},
            {"object_type": "person"},
            {"other": "ignored"},
        ],
        "object_type",
    ) == {
        "organization": 1,
        "person": 2,
    }
