from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from inspect_gmail_pilot_output import inspect_singer_output, write_summary

from gcb.etl.extract.sync_jobs import (
    complete_connector_job,
    connector_job_runs,
    connector_retry_plan,
    fail_connector_job,
    start_connector_job,
)
from gcb.governance.state import create_governed_context_state
from gcb.secrets.env import parse_dotenv_export_lines

REQUIRED_ENV_VARS = (
    "TAP_GMAIL_USER_ID",
    "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID",
    "TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET",
    "TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN",
)
OPTIONAL_ENV_VARS = (
    "TAP_GMAIL_MESSAGES_INCLUDE_SPAM_TRASH",
    "TAP_GMAIL_MESSAGES_Q",
)
DEFAULT_ENV_FILE = Path(".local/gmail-pilot/tap-gmail.env")
DEFAULT_OUTPUT = Path(".local/gmail-pilot/tap-gmail-output.jsonl")
DEFAULT_INSPECTION_OUTPUT = Path(".local/gmail-pilot/inspection-summary.json")
DEFAULT_STATE_INPUT = Path(".local/gmail-pilot/tap-gmail-input-state.json")

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class GmailPilotConfig:
    env_file: Path
    output: Path
    command: tuple[str, ...]
    inspection_output: Path = DEFAULT_INSPECTION_OUTPUT
    state_path: Path | None = None
    state_input_path: Path | None = DEFAULT_STATE_INPUT
    database_url: str | None = None
    connector_name: str = "gmail-pilot"
    retry_failed: bool = False
    retry_base_delay_seconds: int = 300


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Gmail pilot env file: {path}")

    return load_env_lines(path.read_text(encoding="utf-8").splitlines())


def load_env_lines(lines: list[str]) -> dict[str, str]:
    return parse_dotenv_export_lines(lines)


def load_pilot_env(config: GmailPilotConfig, *, runner: Runner = subprocess.run) -> dict[str, str]:
    return load_pilot_env_with_secrets(config)


def load_pilot_env_with_secrets(config: GmailPilotConfig) -> dict[str, str]:
    if not config.env_file.exists():
        raise FileNotFoundError(f"Missing Gmail pilot env file: {config.env_file}")
    return load_env_file(config.env_file)


def validate_required_env(values: Mapping[str, str]) -> list[str]:
    return [key for key in REQUIRED_ENV_VARS if not values.get(key)]


def redacted_summary(values: Mapping[str, str]) -> dict[str, object]:
    return {
        "required": {key: "present" if values.get(key) else "missing" for key in REQUIRED_ENV_VARS},
        "optional": {key: "present" if values.get(key) else "missing" for key in OPTIONAL_ENV_VARS},
    }


def run_gmail_pilot(
    config: GmailPilotConfig,
    *,
    runner: Runner = subprocess.run,
    inspect_output: bool = False,
    now: datetime | None = None,
) -> int:
    sync_state = _sync_state(config)
    retry_run = None
    retry_attempt = 1
    if config.retry_failed and sync_state is not None:
        job_history = connector_job_runs(sync_state.engine, sync_state.connector_job_runs)
        retry = connector_retry_plan(
            job_history,
            connector_name=config.connector_name,
            base_delay_seconds=config.retry_base_delay_seconds,
        )
        if retry is None:
            print(json.dumps({"status": "no_failed_job_to_retry"}, indent=2, sort_keys=True))
            return 0
        if retry is not None:
            if _retry_due_at(retry) > _run_now(now):
                print(
                    json.dumps(
                        {
                            "status": "retry_not_due",
                            "attempt": retry.attempt,
                            "earliest_retry_at": retry.earliest_retry_at,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            retry_run = _latest_failed_connector_run(
                job_history, connector_name=config.connector_name
            )
            retry_attempt = retry.attempt

    env_values = load_pilot_env_with_secrets(config)
    missing = validate_required_env(env_values)
    if missing:
        print(json.dumps(preflight_report(env_values), indent=2, sort_keys=True), file=sys.stderr)
        return 2

    job = None
    if sync_state is not None:
        job = start_connector_job(
            sync_state.engine,
            job_runs=sync_state.connector_job_runs,
            connector_states=sync_state.connector_states,
            connector_name=config.connector_name,
            attempt=retry_attempt,
            input_state=_retry_input_state(retry_run),
            now=now,
        )

    config.output.parent.mkdir(parents=True, exist_ok=True)
    run_env = os.environ.copy()
    run_env.update(env_values)
    command = _command_with_input_state(
        config.command, job=job, state_input_path=config.state_input_path
    )

    with config.output.open("w", encoding="utf-8") as output_file:
        completed = runner(
            command,
            env=run_env,
            stdout=output_file,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    result = {
        "status": "completed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "output": config.output.as_posix(),
        "summary": redacted_summary(env_values),
        "stderr_tail": _tail(completed.stderr),
    }
    if job is not None and sync_state is not None:
        result["job_id"] = job.job_id
        if completed.returncode == 0:
            complete_connector_job(
                sync_state.engine,
                job_runs=sync_state.connector_job_runs,
                connector_states=sync_state.connector_states,
                job_id=job.job_id,
                connector_name=config.connector_name,
                output_state=_latest_singer_state(config.output),
                raw_output_ref=config.output.as_posix(),
            )
        else:
            fail_connector_job(
                sync_state.engine,
                sync_state.connector_job_runs,
                job_id=job.job_id,
                error=_tail(completed.stderr),
            )
    if inspect_output and completed.returncode == 0:
        inspection_summary = inspect_singer_output(config.output)
        write_summary(inspection_summary, config.inspection_output)
        result["inspection_output"] = config.inspection_output.as_posix()

    print(json.dumps(result, indent=2, sort_keys=True))
    return completed.returncode


def preflight_gmail_pilot(
    config: GmailPilotConfig,
    *,
    runner: Runner = subprocess.run,
) -> int:
    try:
        env_values = load_pilot_env_with_secrets(config)
    except FileNotFoundError as error:
        print(
            json.dumps(
                {
                    "status": "missing_credential_source",
                    "error": str(error),
                    "credential_source": "env_file",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    except RuntimeError as error:
        print(
            json.dumps(
                {
                    "status": "credential_source_error",
                    "error": str(error),
                    "credential_source": "env_file",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    report = preflight_report(env_values)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" else 2


def preflight_report(values: Mapping[str, str]) -> dict[str, object]:
    missing = validate_required_env(values)
    return {
        "status": "ready" if not missing else "missing_required_env",
        "missing": missing,
        "summary": redacted_summary(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Gmail connector pilot safely.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--inspection-output", type=Path, default=DEFAULT_INSPECTION_OUTPUT)
    parser.add_argument(
        "--state-path",
        type=Path,
        help="Optional SQLite state path for Gmail pilot job runs and connector state.",
    )
    parser.add_argument(
        "--state-input-path",
        type=Path,
        default=DEFAULT_STATE_INPUT,
        help="Path where stored connector checkpoint is written before passing --state to the tap.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("GCB_DATABASE_URL"),
        help="Optional SQLAlchemy database URL for Gmail pilot job runs and connector state.",
    )
    parser.add_argument("--connector-name", default="gmail-pilot")
    parser.add_argument(
        "--command",
        nargs="+",
        default=["uv", "run", "--with", "meltanolabs-tap-gmail", "tap-gmail"],
        help="Command that emits Singer messages to stdout.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Only validate credential availability without running the Gmail tap.",
    )
    parser.add_argument(
        "--inspect-output",
        action="store_true",
        help="After a successful tap run, write a redacted output-shape inspection summary.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry the latest failed Gmail pilot job when its backoff window is due.",
    )
    parser.add_argument(
        "--retry-base-delay-seconds",
        type=int,
        default=300,
        help="Base retry delay in seconds for failed Gmail pilot jobs.",
    )
    args = parser.parse_args()
    config = GmailPilotConfig(
        env_file=args.env_file,
        output=args.output,
        command=tuple(args.command),
        inspection_output=args.inspection_output,
        state_path=args.state_path,
        state_input_path=args.state_input_path,
        database_url=args.database_url,
        connector_name=args.connector_name,
        retry_failed=args.retry_failed,
        retry_base_delay_seconds=args.retry_base_delay_seconds,
    )
    if args.preflight:
        return preflight_gmail_pilot(config)
    return run_gmail_pilot(config, inspect_output=args.inspect_output)


def _tail(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _sync_state(config: GmailPilotConfig):
    if config.state_path is None and not config.database_url:
        return None
    return create_governed_context_state(
        state_path=config.state_path or ":memory:",
        database_url=config.database_url,
        raw_store_path=None,
    )


def _latest_singer_state(path: Path) -> dict[str, object]:
    latest: dict[str, object] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid Singer JSON on line {line_number}: {error.msg}") from error
        if not isinstance(message, dict) or message.get("type") != "STATE":
            continue
        value = message.get("value")
        if isinstance(value, dict):
            latest = value
    return latest


def _command_with_input_state(
    command: tuple[str, ...],
    *,
    job,
    state_input_path: Path | None,
) -> tuple[str, ...]:
    if job is None or not job.input_state:
        return command
    if state_input_path is None:
        return command
    state_input_path.parent.mkdir(parents=True, exist_ok=True)
    state_input_path.write_text(
        json.dumps(job.input_state, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return (*command, "--state", state_input_path.as_posix())


def _latest_failed_connector_run(
    job_history: list[dict[str, object]],
    *,
    connector_name: str,
) -> dict[str, object] | None:
    failed_runs = [
        run
        for run in job_history
        if run["connector_name"] == connector_name and run["status"] == "failed"
    ]
    if not failed_runs:
        return None
    return max(
        failed_runs,
        key=lambda run: (
            str(run["started_at"]),
            str(run["finished_at"]),
            str(run["job_id"]),
        ),
    )


def _retry_due_at(retry) -> datetime:
    return datetime.fromisoformat(retry.earliest_retry_at)


def _retry_input_state(retry_run: dict[str, object] | None) -> dict[str, object] | None:
    if retry_run is None:
        return None
    input_state = retry_run.get("input_state")
    if isinstance(input_state, dict):
        return input_state
    return None


def _run_now(now: datetime | None) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now
    return datetime.now(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
