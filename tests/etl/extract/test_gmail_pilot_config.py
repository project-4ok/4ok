from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fourok.etl.extract.sync_jobs import connector_checkpoint, connector_job_runs
from fourok.governance.state import create_governed_context_state

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "run_gmail_pilot.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))
SPEC = importlib.util.spec_from_file_location("run_gmail_pilot", SCRIPT_PATH)
assert SPEC is not None
gmail_pilot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gmail_pilot
SPEC.loader.exec_module(gmail_pilot)

GmailPilotConfig = gmail_pilot.GmailPilotConfig
load_env_file = gmail_pilot.load_env_file
load_pilot_env = gmail_pilot.load_pilot_env
load_pilot_env_with_secrets = gmail_pilot.load_pilot_env_with_secrets
preflight_gmail_pilot = gmail_pilot.preflight_gmail_pilot
preflight_report = gmail_pilot.preflight_report
redacted_summary = gmail_pilot.redacted_summary
run_gmail_pilot = gmail_pilot.run_gmail_pilot
validate_required_env = gmail_pilot.validate_required_env


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.envs.append(dict(kwargs.get("env", {})))
        if command[0] == sys.executable:
            return gmail_pilot.subprocess.run(command, **kwargs)
        raise AssertionError(f"Unexpected command: {command}")








def _required_env_text() -> str:
    return "\n".join(
        [
            'export TAP_GMAIL_USER_ID="pilot@example.com"',
            'export TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID="client-id"',
            'export TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET="client-secret"',
            'export TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN="refresh-token"',
        ]
    )


def test_gmail_pilot_env_loader_supports_export_and_quoted_values(tmp_path: Path) -> None:
    env_file = tmp_path / "tap-gmail.env"
    env_file.write_text(
        "\n".join(
            [
                'export TAP_GMAIL_USER_ID="pilot@example.com"',
                "TAP_GMAIL_MESSAGES_INCLUDE_SPAM_TRASH=true",
                "TAP_GMAIL_MESSAGES_Q='newer_than:30d 4OK-PILOT'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    values = load_env_file(env_file)

    assert values["TAP_GMAIL_USER_ID"] == "pilot@example.com"
    assert values["TAP_GMAIL_MESSAGES_INCLUDE_SPAM_TRASH"] == "true"
    assert values["TAP_GMAIL_MESSAGES_Q"] == "newer_than:30d 4OK-PILOT"


def test_gmail_pilot_validation_reports_missing_required_values() -> None:
    missing = validate_required_env({"TAP_GMAIL_USER_ID": "pilot@example.com"})

    assert missing == [
        "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID",
        "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET",
        "TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN",
    ]


def test_gmail_pilot_summary_does_not_expose_secret_values() -> None:
    summary = redacted_summary(
        {
            "TAP_GMAIL_USER_ID": "pilot@example.com",
            "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID": "client-id",
            "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET": "client-secret",
            "TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN": "refresh-token",
            "TAP_GMAIL_MESSAGES_Q": "newer_than:30d 4OK-PILOT",
        }
    )

    serialized = json.dumps(summary)

    assert "client-secret" not in serialized
    assert "refresh-token" not in serialized
    assert summary["required"]["TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET"] == "present"
    assert summary["optional"]["TAP_GMAIL_MESSAGES_INCLUDE_SPAM_TRASH"] == "missing"


def test_gmail_pilot_preflight_report_is_redacted() -> None:
    report = preflight_report(
        {
            "TAP_GMAIL_USER_ID": "pilot@example.com",
            "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID": "client-id",
            "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET": "client-secret",
            "TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN": "refresh-token",
        }
    )

    serialized = json.dumps(report)

    assert report["status"] == "ready"
    assert report["missing"] == []
    assert "client-secret" not in serialized
    assert "refresh-token" not in serialized


def test_gmail_pilot_preflight_reports_missing_file_without_running_tap(
    tmp_path: Path,
    capsys,
) -> None:
    status = preflight_gmail_pilot(
        GmailPilotConfig(
            env_file=tmp_path / "missing.env",
            output=tmp_path / "out.jsonl",
            command=("should-not-run",),
        )
    )
    captured = capsys.readouterr()

    assert status == 2
    assert '"status": "missing_credential_source"' in captured.out
    assert "should-not-run" not in captured.out


def test_gmail_pilot_preflight_reports_missing_required_values(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    env_file.write_text('export TAP_GMAIL_USER_ID="pilot@example.com"\n', encoding="utf-8")

    status = preflight_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=tmp_path / "out.jsonl",
            command=("should-not-run",),
        )
    )
    captured = capsys.readouterr()

    assert status == 2
    assert '"status": "missing_required_env"' in captured.out
    assert "pilot@example.com" not in captured.out
    assert "TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN" in captured.out










def test_gmail_pilot_runner_writes_tap_stdout_without_printing_secrets(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    env_file.write_text(
        "\n".join(
            [
                'export TAP_GMAIL_USER_ID="pilot@example.com"',
                'export TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID="client-id"',
                'export TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET="client-secret"',
                'export TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN="refresh-token"',
            ]
        ),
        encoding="utf-8",
    )

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            command=(
                sys.executable,
                "-c",
                'print(\'{"type":"STATE","value":{"bookmark":"msg-1"}}\')',
            ),
        ),
    )
    captured = capsys.readouterr()

    assert status == 0
    assert output.read_text(encoding="utf-8") == ('{"type":"STATE","value":{"bookmark":"msg-1"}}\n')
    assert "client-secret" not in captured.out
    assert "refresh-token" not in captured.out
    assert '"status": "completed"' in captured.out


def test_gmail_pilot_runner_can_inspect_successful_tap_output(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    inspection_output = tmp_path / "inspection.json"
    env_file.write_text(
        "\n".join(
            [
                'export TAP_GMAIL_USER_ID="pilot@example.com"',
                'export TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID="client-id"',
                'export TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET="client-secret"',
                'export TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN="refresh-token"',
            ]
        ),
        encoding="utf-8",
    )

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            inspection_output=inspection_output,
            command=(
                sys.executable,
                "-c",
                (
                    'print(\'{"type":"RECORD","stream":"messages",'
                    '"record":{"id":"msg-1","thread_id":"thread-1",'
                    '"date":"2026-05-24","body":"secret body"}}\')'
                ),
            ),
        ),
        inspect_output=True,
    )
    captured = capsys.readouterr()
    inspection = json.loads(inspection_output.read_text(encoding="utf-8"))

    assert status == 0
    assert inspection["record_count"] == 1
    assert inspection["streams"][0]["required_presence"] == {
        "body": True,
        "id": True,
        "thread": True,
        "timestamp": True,
    }
    assert "secret body" not in captured.out
    assert "client-secret" not in captured.out
    assert f'"inspection_output": "{inspection_output.as_posix()}"' in captured.out




def test_gmail_pilot_runner_records_successful_job_checkpoint(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    state_path = tmp_path / "gmail-pilot.sqlite"
    env_file.write_text(_required_env_text(), encoding="utf-8")

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            command=(
                sys.executable,
                "-c",
                'print(\'{"type":"STATE","value":{"bookmark":"msg-2"}}\')',
            ),
            state_path=state_path,
        )
    )
    captured = capsys.readouterr()
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )

    assert status == 0
    assert connector_checkpoint(
        state.engine,
        state.connector_states,
        connector_name="gmail-pilot",
    ) == {"bookmark": "msg-2"}
    assert connector_job_runs(state.engine, state.connector_job_runs)[0]["status"] == "succeeded"
    assert '"job_id": "' in captured.out


def test_gmail_pilot_runner_passes_stored_checkpoint_as_state_input(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    state_path = tmp_path / "gmail-pilot.sqlite"
    state_input_path = tmp_path / "tap-state.json"
    env_file.write_text(_required_env_text(), encoding="utf-8")
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    first = gmail_pilot.start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    gmail_pilot.complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=first.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "msg-1"},
    )
    fake_runner = FakeRunner()

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            command=(
                sys.executable,
                "-c",
                'print(\'{"type":"STATE","value":{"bookmark":"msg-2"}}\')',
            ),
            state_path=state_path,
            state_input_path=state_input_path,
        ),
        runner=fake_runner,
    )
    capsys.readouterr()

    assert status == 0
    assert fake_runner.commands[0][-2:] == ["--state", str(state_input_path)]
    assert json.loads(state_input_path.read_text(encoding="utf-8")) == {"bookmark": "msg-1"}
    runs = connector_job_runs(state.engine, state.connector_job_runs)
    rerun = next(run for run in runs if run["job_id"] != "job-1")
    assert rerun["input_state"] == {"bookmark": "msg-1"}


def test_gmail_pilot_runner_records_failed_job_without_checkpoint(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    state_path = tmp_path / "gmail-pilot.sqlite"
    env_file.write_text(_required_env_text(), encoding="utf-8")

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            command=(
                sys.executable,
                "-c",
                "import sys; print('tap failed', file=sys.stderr); raise SystemExit(7)",
            ),
            state_path=state_path,
        )
    )
    captured = capsys.readouterr()
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )

    assert status == 7
    assert (
        connector_checkpoint(
            state.engine,
            state.connector_states,
            connector_name="gmail-pilot",
        )
        == {}
    )
    runs = connector_job_runs(state.engine, state.connector_job_runs)
    assert runs[0]["status"] == "failed"
    assert runs[0]["error"] == "tap failed\n"
    assert runs[0]["started_at"]
    assert runs[0]["finished_at"]
    assert datetime.fromisoformat(runs[0]["started_at"])
    assert datetime.fromisoformat(runs[0]["finished_at"])
    assert '"status": "failed"' in captured.out


def test_gmail_pilot_retry_mode_refuses_run_before_retry_is_due(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    state_path = tmp_path / "gmail-pilot.sqlite"
    env_file.write_text(_required_env_text(), encoding="utf-8")
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    succeeded = gmail_pilot.start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
        now=datetime(2026, 5, 24, 10, 0, tzinfo=UTC),
    )
    gmail_pilot.complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=succeeded.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "msg-1"},
        now=datetime(2026, 5, 24, 10, 1, tzinfo=UTC),
    )
    failed = gmail_pilot.start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
        attempt=2,
        now=datetime(2026, 5, 24, 10, 2, tzinfo=UTC),
    )
    gmail_pilot.fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=failed.job_id,
        error="tap failed\n",
        now=datetime(2026, 5, 24, 10, 2, tzinfo=UTC),
    )
    fake_runner = FakeRunner()

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            command=("should-not-run",),
            state_path=state_path,
            retry_failed=True,
            retry_base_delay_seconds=300,
        ),
        runner=fake_runner,
        now=datetime(2026, 5, 24, 10, 11, tzinfo=UTC),
    )
    captured = capsys.readouterr()

    assert status == 0
    assert fake_runner.commands == []
    assert output.exists() is False
    assert json.loads(captured.out) == {
        "attempt": 3,
        "earliest_retry_at": "2026-05-24T10:12:00+00:00",
        "status": "retry_not_due",
    }


def test_gmail_pilot_retry_mode_does_not_start_fresh_sync_without_failed_job(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "tap-gmail.env"
    output = tmp_path / "gmail-output.jsonl"
    state_path = tmp_path / "gmail-pilot.sqlite"
    env_file.write_text(_required_env_text(), encoding="utf-8")
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    succeeded = gmail_pilot.start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    gmail_pilot.complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=succeeded.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "msg-1"},
    )
    fake_runner = FakeRunner()

    status = run_gmail_pilot(
        GmailPilotConfig(
            env_file=env_file,
            output=output,
            command=("should-not-run",),
            state_path=state_path,
            retry_failed=True,
        ),
        runner=fake_runner,
    )
    captured = capsys.readouterr()

    assert status == 0
    assert fake_runner.commands == []
    assert output.exists() is False
    assert json.loads(captured.out) == {"status": "no_failed_job_to_retry"}
