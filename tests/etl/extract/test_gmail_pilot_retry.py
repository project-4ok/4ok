from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fourok.etl.extract.sync_jobs import connector_job_runs
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


def test_gmail_pilot_retry_mode_starts_due_retry_from_failed_input_state(
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
            command=(
                sys.executable,
                "-c",
                'print(\'{"type":"STATE","value":{"bookmark":"msg-2"}}\')',
            ),
            state_path=state_path,
            state_input_path=state_input_path,
            retry_failed=True,
            retry_base_delay_seconds=300,
        ),
        runner=fake_runner,
        now=datetime(2026, 5, 24, 10, 12, tzinfo=UTC),
    )
    captured = capsys.readouterr()
    runs = connector_job_runs(state.engine, state.connector_job_runs)
    retried = next(run for run in runs if run["job_id"] not in {"job-1", "job-2"})

    assert status == 0
    assert fake_runner.commands[0][-2:] == ["--state", str(state_input_path)]
    assert json.loads(state_input_path.read_text(encoding="utf-8")) == {"bookmark": "msg-1"}
    assert retried["attempt"] == 3
    assert retried["input_state"] == {"bookmark": "msg-1"}
    assert '"status": "completed"' in captured.out


def test_gmail_pilot_non_retry_run_is_unchanged_when_latest_job_failed(
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
    failed = gmail_pilot.start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
        attempt=2,
    )
    gmail_pilot.fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=failed.job_id,
        error="tap failed\n",
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
    runs = connector_job_runs(state.engine, state.connector_job_runs)
    normal = next(run for run in runs if run["job_id"] not in {"job-1", "job-2"})

    assert status == 0
    assert normal["attempt"] == 1
    assert normal["input_state"] == {"bookmark": "msg-1"}
    assert fake_runner.commands[0][-2:] == ["--state", str(state_input_path)]
