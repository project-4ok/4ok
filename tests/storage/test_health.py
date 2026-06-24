from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.storage.health import check_runtime_health


def test_check_runtime_health_reports_database_without_records_as_failed(tmp_path: Path) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        raw_store_path=None,
    )

    report = check_runtime_health(state)

    assert report == {
        "status": "failed",
        "checks": [
            {
                "name": "database",
                "status": "ok",
                "detail": "connected",
                "dialect": "sqlite",
            },
            {
                "name": "source_records",
                "status": "failed",
                "detail": "no active source records found",
                "count": 0,
            },
            {
                "name": "retrieval_records",
                "status": "failed",
                "detail": "no current retrieval records found",
                "count": 0,
            },
        ],
    }


def test_check_runtime_health_reports_online_when_source_and_retrieval_records_exist(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:health",
                source_system="slack",
                source_id="health",
                record_type="message",
                title="Health smoke",
                body="4OK health command should see records.",
                occurred_at="2026-06-15T12:00:00+00:00",
            )
        ]
    )
    context.build_vector_index()

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    report = check_runtime_health(state)

    assert report["status"] == "ok"
    assert report["checks"] == [
        {
            "name": "database",
            "status": "ok",
            "detail": "connected",
            "dialect": "sqlite",
        },
        {
            "name": "source_records",
            "status": "ok",
            "detail": "active source records found",
            "count": 1,
        },
        {
            "name": "retrieval_records",
            "status": "ok",
            "detail": "current retrieval records found",
            "count": 1,
        },
    ]


def test_check_runtime_health_reports_database_connection_failure() -> None:
    engine = create_engine("sqlite:////path/that/does/not/exist/fourok.sqlite")

    report = check_runtime_health(SimpleNamespace(engine=engine, raw_store=None))

    assert report["status"] == "failed"
    assert report["checks"][0]["name"] == "database"
    assert report["checks"][0]["status"] == "failed"
