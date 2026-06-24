from datetime import UTC, datetime

from fourok.etl.extract.sync_jobs import (
    complete_connector_job,
    connector_checkpoint,
    connector_job_runs,
    connector_retry_plan,
    fail_connector_job,
    start_connector_job,
    try_start_connector_job,
)
from fourok.governance.state import create_governed_context_state


def test_connector_job_success_updates_checkpoint() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    started_at = datetime(2026, 5, 24, 10, 0, tzinfo=UTC)
    finished_at = datetime(2026, 5, 24, 10, 1, tzinfo=UTC)

    run = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
        now=started_at,
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=run.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "message-2"},
        raw_output_ref=".local/gmail-pilot/tap-gmail-output.jsonl",
        now=finished_at,
    )

    assert run.input_state == {}
    assert connector_checkpoint(
        state.engine,
        state.connector_states,
        connector_name="gmail-pilot",
    ) == {"bookmark": "message-2"}
    assert connector_job_runs(state.engine, state.connector_job_runs) == [
        {
            "job_id": "job-1",
            "connector_name": "gmail-pilot",
            "status": "succeeded",
            "attempt": 1,
            "started_at": "2026-05-24T10:00:00+00:00",
            "finished_at": "2026-05-24T10:01:00+00:00",
            "input_state": {},
            "output_state": {"bookmark": "message-2"},
            "raw_output_ref": ".local/gmail-pilot/tap-gmail-output.jsonl",
            "error": "",
        }
    ]


def test_connector_job_start_snapshots_latest_checkpoint() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )

    first = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=first.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "message-2"},
    )
    second = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
    )

    assert second.input_state == {"bookmark": "message-2"}


def test_try_start_connector_job_prevents_overlapping_running_jobs() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )

    first = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    second = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
    )

    assert first.started is not None
    assert first.running is None
    assert second.started is None
    assert second.running is not None
    assert second.running["job_id"] == "job-1"
    stored_job_ids = [
        job["job_id"] for job in connector_job_runs(state.engine, state.connector_job_runs)
    ]
    assert stored_job_ids == ["job-1"]


def test_try_start_connector_job_allows_next_run_after_completion() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    first = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    assert first.started is not None
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=first.started.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "message-2"},
    )

    second = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
    )

    assert second.started is not None
    assert second.running is None
    assert second.started.input_state == {"bookmark": "message-2"}


def test_connector_job_start_reuses_exact_nested_singer_state() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    singer_state = {
        "bookmarks": {
            "messages": {
                "replication_key": "historyId",
                "replication_key_value": "9001",
                "partitions": {
                    "primary": {"history_id": "9001", "message_id": "msg-9001"},
                },
            }
        },
        "currently_syncing": "messages",
    }

    first = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=first.job_id,
        connector_name="gmail-pilot",
        output_state=singer_state,
    )

    second = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
    )

    assert second.input_state == singer_state
    latest_run = connector_job_runs(state.engine, state.connector_job_runs)[-1]
    assert latest_run["input_state"] == singer_state


def test_failed_connector_job_records_error_without_replacing_checkpoint() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    first = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=first.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "message-2"},
    )
    failed = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
        attempt=2,
    )

    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=failed.job_id,
        error="tap exited with status 1",
    )

    assert connector_checkpoint(
        state.engine,
        state.connector_states,
        connector_name="gmail-pilot",
    ) == {"bookmark": "message-2"}
    failed_run = connector_job_runs(state.engine, state.connector_job_runs)[-1]
    assert failed_run["job_id"] == "job-2"
    assert failed_run["connector_name"] == "gmail-pilot"
    assert failed_run["status"] == "failed"
    assert failed_run["attempt"] == 2
    assert failed_run["input_state"] == {"bookmark": "message-2"}
    assert failed_run["output_state"] == {}
    assert failed_run["raw_output_ref"] == ""
    assert failed_run["error"] == "tap exited with status 1"
    assert failed_run["started_at"]
    assert failed_run["finished_at"]
    assert datetime.fromisoformat(failed_run["started_at"])
    assert datetime.fromisoformat(failed_run["finished_at"])


def test_connector_retry_plan_after_failed_run_uses_next_attempt_and_base_delay() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    started_at = datetime(2026, 5, 24, 10, 0, tzinfo=UTC)
    finished_at = datetime(2026, 5, 24, 10, 1, tzinfo=UTC)

    run = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
        attempt=1,
        now=started_at,
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=run.job_id,
        error="tap exited with status 1",
        now=finished_at,
    )

    retry = connector_retry_plan(
        connector_job_runs(state.engine, state.connector_job_runs),
        connector_name="gmail-pilot",
        base_delay_seconds=300,
    )

    assert retry is not None
    assert retry.attempt == 2
    assert retry.earliest_retry_at == "2026-05-24T10:06:00+00:00"


def test_connector_retry_plan_increases_delay_for_repeated_failures() -> None:
    retry = connector_retry_plan(
        [
            {
                "job_id": "job-1",
                "connector_name": "gmail-pilot",
                "status": "failed",
                "attempt": 3,
                "started_at": "2026-05-24T10:00:00+00:00",
                "finished_at": "2026-05-24T10:01:00+00:00",
                "input_state": {},
                "output_state": {},
                "raw_output_ref": "",
                "error": "tap exited with status 1",
            }
        ],
        connector_name="gmail-pilot",
        base_delay_seconds=300,
    )

    assert retry is not None
    assert retry.attempt == 4
    assert retry.earliest_retry_at == "2026-05-24T10:21:00+00:00"


def test_connector_retry_plan_returns_none_after_successful_run() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    started_at = datetime(2026, 5, 24, 10, 0, tzinfo=UTC)
    finished_at = datetime(2026, 5, 24, 10, 1, tzinfo=UTC)

    run = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
        attempt=1,
        now=started_at,
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=run.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "message-2"},
        now=finished_at,
    )

    assert (
        connector_retry_plan(
            connector_job_runs(state.engine, state.connector_job_runs),
            connector_name="gmail-pilot",
            base_delay_seconds=300,
        )
        is None
    )


def test_connector_retry_plan_returns_none_while_latest_run_is_running() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    failed_at = datetime(2026, 5, 24, 10, 1, tzinfo=UTC)
    retry_started_at = datetime(2026, 5, 24, 10, 6, tzinfo=UTC)
    first = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
        attempt=1,
        now=datetime(2026, 5, 24, 10, 0, tzinfo=UTC),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=first.job_id,
        error="tap exited with status 1",
        now=failed_at,
    )
    start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-2",
        attempt=2,
        now=retry_started_at,
    )

    assert (
        connector_retry_plan(
            connector_job_runs(state.engine, state.connector_job_runs),
            connector_name="gmail-pilot",
            base_delay_seconds=300,
        )
        is None
    )


def test_connector_retry_plan_handles_failed_run_created_without_injected_now() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    run = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail-pilot",
        job_id="job-1",
        attempt=1,
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=run.job_id,
        error="tap exited with status 1",
    )

    failed_run = connector_job_runs(state.engine, state.connector_job_runs)[0]
    retry = connector_retry_plan(
        [failed_run],
        connector_name="gmail-pilot",
        base_delay_seconds=300,
    )

    assert failed_run["started_at"]
    assert failed_run["finished_at"]
    assert retry is not None
    assert retry.attempt == 2
    assert datetime.fromisoformat(retry.earliest_retry_at)
