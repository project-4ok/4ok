from pathlib import Path

from gcb.etl.extract.source_records import SourceRecord
from gcb.governance import GovernedContext, SourceChange
from gcb.runtime.operator_live import (
    build_operator_live_dry_run,
    build_operator_live_report,
    host_database_url,
    redacted_database_url,
)


def test_operator_live_dry_run_reports_plan_without_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GCB_DATABASE_URL=postgresql+psycopg://gcb:secret@localhost:5432/gcb\n"
        "SLACK_BOT_TOKEN=secret-value\n",
        encoding="utf-8",
    )

    report = build_operator_live_dry_run(
        project_root=tmp_path,
        raw_landing=Path(".local/raw/singer"),
        state_path=Path(".local/dagster/gcb-state.sqlite"),
        database_url="postgresql+psycopg://gcb:secret@localhost:5432/gcb",
        start_dagster=True,
    )

    assert report == {
        "mode": "dry-run",
        "dagster": {
            "start_command": [
                "docker",
                "compose",
                "--profile",
                "pipeline",
                "up",
                "--build",
                "--force-recreate",
                "-d",
                "postgres",
                "dagster-postgres",
                "dagster-code",
                "dagster-webserver",
                "dagster-daemon",
            ],
            "status_command": ["docker", "compose", "--profile", "pipeline", "ps"],
            "status": "not_started",
        },
        "raw_landing_path": str(tmp_path / ".local/raw/singer"),
        "gcb_database_url": "postgresql+psycopg://gcb:[REDACTED]@localhost:5432/gcb",
        "state_path": str(tmp_path / ".local/dagster/gcb-state.sqlite"),
        "live_assets": [
            "meltano_slack_live_raw_landing",
            "gcb_slack_live_source_records_from_raw_landing",
            "meltano_twenty_live_raw_landing",
            "gcb_twenty_live_source_records_from_raw_landing",
            "meltano_linear_live_raw_landing",
            "gcb_linear_live_source_records_from_raw_landing",
            "meltano_google_drive_live_raw_landing",
            "gcb_google_drive_live_source_records_from_raw_landing",
        ],
        "source_record_counts_by_source_system": {},
        "retrieval_count": 0,
    }


def test_operator_live_dry_run_reports_host_database_url_for_compose_postgres(
    tmp_path: Path,
) -> None:
    report = build_operator_live_dry_run(
        project_root=tmp_path,
        raw_landing=Path(".local/raw/singer"),
        state_path=Path(".local/dagster/gcb-state.sqlite"),
        database_url=host_database_url("postgresql+psycopg://gcb:secret@postgres:5432/gcb"),
        start_dagster=True,
    )

    assert report["gcb_database_url"] == "postgresql+psycopg://gcb:[REDACTED]@127.0.0.1:5432/gcb"


def test_operator_live_report_counts_source_records_and_retrieval(tmp_path: Path) -> None:
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
                body="Alpha customer needs follow-up.",
            ),
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Linear issue",
                body="Alpha customer support issue.",
            ),
            SourceRecord(
                source_ref="slack:message:2",
                source_system="slack",
                source_id="2",
                record_type="message",
                title="Slack message",
                body="Beta customer needs follow-up.",
            ),
        ]
    )

    report = build_operator_live_report(
        project_root=tmp_path,
        raw_landing=Path(".local/raw/singer"),
        state_path=state_path,
        database_url="",
        dagster_status="materialized",
        dagster_assets=["gcb_operator_dashboard"],
    )

    assert report == {
        "mode": "live",
        "dagster": {
            "status": "materialized",
            "assets": ["gcb_operator_dashboard"],
        },
        "raw_landing_path": str(tmp_path / ".local/raw/singer"),
        "gcb_database_url": "",
        "state_path": str(state_path),
        "source_record_counts_by_source_system": {
            "linear": 1,
            "slack": 2,
        },
        "retrieval_count": 3,
    }


def test_operator_live_report_counts_only_active_source_records(tmp_path: Path) -> None:
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

    report = build_operator_live_report(
        project_root=tmp_path,
        raw_landing=Path(".local/raw/singer"),
        state_path=state_path,
        database_url="",
        dagster_status="materialized",
        dagster_assets=["gcb_operator_dashboard"],
    )

    assert report["source_record_counts_by_source_system"] == {"linear": 1, "twenty": 1}


def test_host_database_url_maps_compose_hostname_to_loopback_for_host_materialization() -> None:
    assert (
        host_database_url("postgresql+psycopg://gcb:secret@postgres:5432/gcb")
        == "postgresql+psycopg://gcb:secret@127.0.0.1:5432/gcb"
    )
    assert (
        host_database_url("postgresql+psycopg://gcb:secret@db.internal:5432/gcb")
        == "postgresql+psycopg://gcb:secret@db.internal:5432/gcb"
    )


def test_redacted_database_url_hides_password_and_query_secret() -> None:
    assert (
        redacted_database_url(
            "postgresql+psycopg://gcb:secret@localhost:5432/gcb?sslpassword=hidden"
        )
        == "postgresql+psycopg://gcb:[REDACTED]@localhost:5432/gcb?sslpassword=[REDACTED]"
    )
