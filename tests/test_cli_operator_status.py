import json
from datetime import UTC, datetime
from pathlib import Path

from fourok.cli import main
from fourok.cli_parts.commands_runtime import host_operator_database_url
from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.extract.sync_jobs import complete_connector_job, start_connector_job
from fourok.governance import GovernedContext, SourceChange
from fourok.governance.state import create_governed_context_state
from fourok.runtime.dashboard import operator_status


def test_operator_status_default_resolves_compose_database_url_from_env_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FOUR_OK_DATABASE_URL", raising=False)
    monkeypatch.setattr("fourok.cli_parts.commands_runtime._running_app_database_url", lambda: "")
    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=secret\n"
        "FOUR_OK_DATABASE_URL=postgresql+psycopg://fourok:secret@postgres:5432/fourok\n",
        encoding="utf-8",
    )

    database_url = host_operator_database_url(
        state=Path(".fourok-state.sqlite"),
        state_explicit=False,
        explicit_database_url=None,
    )

    assert database_url == "postgresql+psycopg://fourok:secret@127.0.0.1:5432/fourok"


def test_operator_status_default_prefers_compose_env_over_stale_shell_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "FOUR_OK_DATABASE_URL",
        "postgresql+psycopg://fourok:stale@127.0.0.1:5432/fourok",
    )
    monkeypatch.setattr("fourok.cli_parts.commands_runtime._running_app_database_url", lambda: "")
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.operator_environment",
        lambda _root: {
            "FOUR_OK_DATABASE_URL": "postgresql+psycopg://fourok:fresh@postgres:5432/fourok",
        },
    )

    database_url = host_operator_database_url(
        state=Path(".fourok-state.sqlite"),
        state_explicit=False,
        explicit_database_url=None,
    )

    assert database_url == "postgresql+psycopg://fourok:fresh@127.0.0.1:5432/fourok"


def test_operator_status_default_prefers_running_app_database_url(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "FOUR_OK_DATABASE_URL",
        "postgresql+psycopg://fourok:stale@127.0.0.1:5432/fourok",
    )
    (tmp_path / ".env").write_text(
        "FOUR_OK_DATABASE_URL=postgresql+psycopg://fourok:dotenv@postgres:5432/fourok\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime._running_app_database_url",
        lambda: "postgresql+psycopg://fourok:running@postgres:5432/fourok",
    )

    database_url = host_operator_database_url(
        state=Path(".fourok-state.sqlite"),
        state_explicit=False,
        explicit_database_url=None,
    )

    assert database_url == "postgresql+psycopg://fourok:running@127.0.0.1:5432/fourok"


def test_running_app_database_url_discovers_compose_app_container(monkeypatch) -> None:
    from fourok.cli_parts import commands_runtime

    calls: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return type("Result", (), {"returncode": 0, "stdout": "container-123\n"})()
        if command == [
            "docker",
            "exec",
            "container-123",
            "printenv",
            "FOUR_OK_DATABASE_URL",
        ]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "postgresql+psycopg://fourok:running@postgres:5432/fourok\n",
                },
            )()
        raise AssertionError(command)

    monkeypatch.setattr(commands_runtime.subprocess, "run", fake_run)

    assert (
        commands_runtime._running_app_database_url()
        == "postgresql+psycopg://fourok:running@postgres:5432/fourok"
    )
    assert calls == [
        ("docker", "compose", "ps", "-q", "app"),
        ("docker", "exec", "container-123", "printenv", "FOUR_OK_DATABASE_URL"),
    ]


def test_running_app_database_url_falls_back_to_docker_labels_when_compose_env_drifts(
    monkeypatch,
) -> None:
    from fourok.cli_parts import commands_runtime

    calls: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return type(
                "Result",
                (),
                {"returncode": 1, "stdout": "", "stderr": "POSTGRES_PASSWORD is missing"},
            )()
        if command == [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=fourok",
            "--filter",
            "label=com.docker.compose.service=app",
            "--format",
            "{{.ID}}",
        ]:
            return type("Result", (), {"returncode": 0, "stdout": "label-container\n"})()
        if command == [
            "docker",
            "exec",
            "label-container",
            "printenv",
            "FOUR_OK_DATABASE_URL",
        ]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "postgresql+psycopg://fourok:running@postgres:5432/fourok\n",
                },
            )()
        raise AssertionError(command)

    monkeypatch.setattr(commands_runtime.subprocess, "run", fake_run)

    assert (
        commands_runtime._running_app_database_url()
        == "postgresql+psycopg://fourok:running@postgres:5432/fourok"
    )
    assert calls == [
        ("docker", "compose", "ps", "-q", "app"),
        (
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=fourok",
            "--filter",
            "label=com.docker.compose.service=app",
            "--format",
            "{{.ID}}",
        ),
        ("docker", "exec", "label-container", "printenv", "FOUR_OK_DATABASE_URL"),
    ]


def test_operator_status_explicit_state_without_database_url_uses_state_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FOUR_OK_DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "FOUR_OK_DATABASE_URL=postgresql+psycopg://fourok:secret@postgres:5432/fourok\n",
        encoding="utf-8",
    )

    database_url = host_operator_database_url(
        state=tmp_path / "fixture.sqlite",
        state_explicit=True,
        explicit_database_url=None,
    )

    assert database_url is None


def test_cli_health_defaults_to_host_runtime_database(capsys, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_create_state(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.operator_environment",
        lambda _root: {
            "FOUR_OK_DATABASE_URL": "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
        },
    )
    monkeypatch.setattr("fourok.cli_parts.commands_runtime._running_app_database_url", lambda: "")
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.create_governed_context_state",
        fake_create_state,
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.check_runtime_health",
        lambda _state: {"status": "ok", "checks": []},
    )
    monkeypatch.setattr("sys.argv", ["fourok", "health"])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"status": "ok", "checks": []}
    assert calls[0]["database_url"] == "postgresql+psycopg://fourok:secret@127.0.0.1:5432/fourok"


def test_cli_health_keeps_explicit_database_url_container_valid(capsys, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_create_state(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.create_governed_context_state",
        fake_create_state,
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.check_runtime_health",
        lambda _state: {"status": "ok", "checks": []},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "health",
            "--database-url",
            "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out) == {"status": "ok", "checks": []}
    assert calls[0]["database_url"] == "postgresql+psycopg://fourok:secret@postgres:5432/fourok"


def test_cli_health_keeps_explicit_state_on_sqlite_path(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    calls: list[dict[str, object]] = []

    def fake_create_state(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.operator_environment",
        lambda _root: {
            "FOUR_OK_DATABASE_URL": "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
        },
    )
    monkeypatch.setattr("fourok.cli_parts.commands_runtime._running_app_database_url", lambda: "")
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.create_governed_context_state",
        fake_create_state,
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.check_runtime_health",
        lambda _state: {"status": "ok", "checks": []},
    )
    monkeypatch.setattr("sys.argv", ["fourok", "health", "--state", str(state)])

    main()

    assert json.loads(capsys.readouterr().out) == {"status": "ok", "checks": []}
    assert calls[0]["state_path"] == state
    assert calls[0]["database_url"] is None


def test_cli_operator_status_keeps_explicit_default_state_path(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / ".fourok-state.sqlite"
    calls: list[object] = []

    def fake_context_state(args):
        calls.append(args)
        return object()

    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.operator_environment",
        lambda _root: {
            "FOUR_OK_DATABASE_URL": "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
        },
    )
    monkeypatch.setattr("fourok.cli_parts.commands_runtime._running_app_database_url", lambda: "")
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime._context_state_from_args",
        fake_context_state,
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.operator_status",
        lambda *_args, **_kwargs: {"status": "ok"},
    )

    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "operator-status", "--state", str(state)],
    )

    main()

    assert json.loads(capsys.readouterr().out) == {"status": "ok"}
    assert calls[0].state == state
    assert calls[0].database_url is None


def test_operator_status_counts_only_active_imported_source_records(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Active issue",
                body="Active issue body.",
            ),
            SourceRecord(
                source_ref="linear:issue:OPS-2",
                source_system="linear",
                source_id="OPS-2",
                record_type="work_item",
                title="Deleted issue",
                body="Deleted issue body.",
            ),
            SourceRecord(
                source_ref="twenty:company:1",
                source_system="twenty",
                source_id="1",
                record_type="organization",
                title="Active company",
                body="Active company body.",
            ),
        ]
    )
    context.apply_source_changes(
        [
            SourceChange(
                operation="delete",
                source_ref="linear:issue:OPS-2",
                reason="missing_from_latest_snapshot",
            )
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )

    output = operator_status(state)

    assert output["imported_items_by_source"] == {"linear": 1, "twenty": 1}
    assert output["imported_items_by_source_record_type"] == {
        "linear": {"work_item": 1},
        "twenty": {"organization": 1},
    }


def test_cli_operator_status_prints_compact_import_counts_and_freshness(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FOUR_OK_DATABASE_URL", raising=False)
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:1",
                source_system="slack",
                source_id="1",
                record_type="message",
                title="Slack message",
                body="Alpha renewal needs follow-up.",
            ),
            SourceRecord(
                source_ref="slack:message:2",
                source_system="slack",
                source_id="2",
                record_type="message",
                title="Slack message",
                body="Beta renewal needs follow-up.",
            ),
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Linear issue",
                body="Alpha support issue.",
            ),
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    started = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="slack-live",
        job_id="job-slack-1",
        now=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=started.job_id,
        connector_name="slack-live",
        output_state={"freshness_status": "fresh", "idempotency_status": "recorded"},
        raw_output_ref=".local/recurring-live-ingestion/slack",
        now=datetime(2026, 6, 9, 10, 2, tzinfo=UTC),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "operator-status",
            "--state",
            str(state_path),
            "--now",
            "2026-06-09T10:02:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "ok",
        "imported_items_by_source": {
            "linear": 1,
            "slack": 2,
        },
        "imported_items_by_source_record_type": {
            "linear": {"work_item": 1},
            "slack": {"message": 2},
        },
        "retrieval_records": {
            "total": 3,
            "by_status": {"current": 3},
        },
        "connector_jobs": {
            "latest": {
                "connector_name": "slack-live",
                "status": "succeeded",
                "started_at": "2026-06-09T10:00:00+00:00",
                "finished_at": "2026-06-09T10:02:00+00:00",
                "raw_output_ref": ".local/recurring-live-ingestion/slack",
            },
            "by_status": {"succeeded": 1},
        },
        "freshness": {
            "latest_checkpoint_at": "2026-06-09T10:02:00+00:00",
            "latest_finished_at": "2026-06-09T10:02:00+00:00",
            "live_ingestion": {
                "status": "attention_required",
                "stale_after_minutes": 60,
                "sources": {
                    "google_drive": {
                        "age_seconds": None,
                        "connector_name": "google_drive-live",
                        "error": "",
                        "freshness_status": "missing",
                        "idempotency_status": "missing",
                        "latest_finished_at": "",
                        "latest_started_at": "",
                        "latest_status": "missing",
                        "raw_output_ref": "",
                        "source_record_count": None,
                    },
                    "linear": {
                        "age_seconds": None,
                        "connector_name": "linear-live",
                        "error": "",
                        "freshness_status": "missing",
                        "idempotency_status": "missing",
                        "latest_finished_at": "",
                        "latest_started_at": "",
                        "latest_status": "missing",
                        "raw_output_ref": "",
                        "source_record_count": None,
                    },
                    "slack": {
                        "age_seconds": 0,
                        "connector_name": "slack-live",
                        "error": "",
                        "freshness_status": "fresh",
                        "idempotency_status": "recorded",
                        "latest_finished_at": "2026-06-09T10:02:00+00:00",
                        "latest_started_at": "2026-06-09T10:00:00+00:00",
                        "latest_status": "succeeded",
                        "raw_output_ref": ".local/recurring-live-ingestion/slack",
                        "source_record_count": None,
                    },
                    "twenty": {
                        "age_seconds": None,
                        "connector_name": "twenty-live",
                        "error": "",
                        "freshness_status": "missing",
                        "idempotency_status": "missing",
                        "latest_finished_at": "",
                        "latest_started_at": "",
                        "latest_status": "missing",
                        "raw_output_ref": "",
                        "source_record_count": None,
                    },
                },
            },
        },
    }
