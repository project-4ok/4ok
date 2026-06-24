from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text

from fourok.runtime.metrics_exporter import (
    collect_runtime_metrics,
    render_prometheus_metrics,
)


def test_metrics_exporter_renders_dagster_run_and_source_freshness_metrics(tmp_path: Path) -> None:
    state_path = tmp_path / "context.sqlite"
    with sqlite3.connect(state_path) as connection:
        connection.executescript(
            """
            create table source_records (
              source_ref text primary key,
              source_system text not null,
              record_type text not null,
              updated_at text not null,
              occurred_at text not null default '',
              lifecycle_state text not null,
              metadata_json text not null default '{}'
            );
            insert into source_records values
              ('slack:1', 'slack', 'message', '2026-06-09T19:10:00+00:00',
               '2026-06-09T19:10:00+00:00', 'active', '{}'),
              ('slack:2', 'slack', 'message', '',
               '2026-06-09T19:25:00+00:00', 'active', '{}'),
              ('linear:1', 'linear', 'work_item', '2026-06-09T19:15:30+00:00',
               '2026-06-09T19:14:00+00:00', 'active', '{}'),
              ('twenty:1', 'twenty', 'organization', '1780063291', '', 'active', '{}'),
              ('drive:image-1', 'google_drive', 'document', '2026-06-09T19:20:00+00:00',
               '', 'active',
               '{"mime_type": "image/png", "content_status": "metadata_only", '
               || '"export_status": "unsupported_mime_type"}'),
              ('linear:2', 'linear', 'work_item', '', '', 'deleted', '{}');
            create table raw_landed_records (
              source_system text not null,
              stream text not null
            );
            insert into raw_landed_records values
              ('slack', 'slack_messages'),
              ('slack', 'slack_messages'),
              ('linear', 'linear_issues');
            create table canonical_objects (
              object_id text primary key,
              object_type text not null
            );
            insert into canonical_objects values
              ('canonical:person:1', 'person'),
              ('canonical:company:1', 'company'),
              ('canonical:company:2', 'company');
            create table entity_links (
              link_id text primary key,
              relationship text not null
            );
            insert into entity_links values
              ('link:1', 'mentions'),
              ('link:2', 'owns');
            create table retrieval_records (
              retrieval_ref text primary key,
              source_ref text not null,
              status text not null
            );
            insert into retrieval_records values
              ('retrieval:slack:1', 'slack:1', 'current'),
              ('retrieval:linear:1', 'linear:1', 'current');
            create table chunk_embeddings (
              source_ref text not null,
              chunk_index integer not null,
              text text not null,
              embedding text not null,
              primary key (source_ref, chunk_index)
            );
            insert into chunk_embeddings values
              ('slack:1', 0, 'Slack body', '[0.1, 0.2]');
            create table retrieval_query_events (
              event_id text primary key,
              occurred_at text not null,
              status text not null,
              retriever_set text not null,
              requested_limit integer not null,
              candidate_limit integer not null,
              pre_rerank_candidates integer not null,
              keyword_candidates integer not null,
              vector_candidates integer not null,
              distinct_sources integer not null,
              returned_results integer not null,
              duration_ms real not null
            );
            insert into retrieval_query_events values
              ('retrieval-query:1', '2026-06-09T19:30:00+00:00', 'succeeded',
               'keyword,vector', 5, 40, 17, 11, 9, 13, 5, 42.5),
              ('retrieval-query:2', '2026-06-09T19:31:00+00:00', 'succeeded',
               'keyword', 3, 20, 0, 0, 0, 0, 0, 18.0),
              ('retrieval-query:3', '2026-06-09T19:32:00+00:00', 'failed',
               'vector', 5, 40, 0, 0, 0, 0, 0, 3.5);
            create table webhook_events (
              event_id text primary key,
              source_system text not null,
              status text not null
            );
            insert into webhook_events values
              ('evt-1', 'linear', 'pending'),
              ('evt-2', 'slack', 'processed');
            create table connector_job_runs (
              job_id text primary key,
              connector_name text not null,
              status text not null,
              started_at text not null,
              finished_at text not null
            );
            insert into connector_job_runs values
              ('job-1', 'slack', 'success',
               '2026-06-09T19:00:00+00:00', '2026-06-09T19:01:00+00:00'),
              ('job-2', 'linear', 'failed',
               '2026-06-09T19:02:00+00:00', '2026-06-09T19:03:00+00:00');
            """
        )

    def fake_graphql(_url: str, _query: str, _variables=None):
        return {
            "data": {
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [
                        {
                            "name": "__repository__",
                            "location": {"name": "fourok_pipeline"},
                            "pipelines": [{"name": "fourok_hourly_live_backfill"}],
                            "schedules": [
                                {
                                    "name": "fourok_hourly_live_backfill_schedule",
                                    "scheduleState": {"status": "RUNNING"},
                                }
                            ],
                            "sensors": [
                                {
                                    "name": "fourok_webhook_backlog_sensor",
                                    "sensorState": {"status": "RUNNING"},
                                }
                            ],
                        }
                    ],
                },
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "run-1",
                            "status": "SUCCESS",
                            "startTime": 1781028000.0,
                            "endTime": 1781028065.0,
                            "stepStats": [
                                {
                                    "stepKey": "meltano_slack_live_raw_landing",
                                    "status": "SUCCESS",
                                    "startTime": 1781028001.0,
                                    "endTime": 1781028011.0,
                                },
                                {
                                    "stepKey": "fourok_retrieval_records",
                                    "status": "FAILURE",
                                    "startTime": 1781028011.0,
                                    "endTime": 1781028021.0,
                                },
                            ],
                        }
                    ],
                },
            }
        }

    metrics = collect_runtime_metrics(
        dagster_url="http://dagster.example/graphql",
        state_path=state_path,
        graphql=fake_graphql,
    )
    text = render_prometheus_metrics(metrics)

    assert 'fourok_dagster_run_status{job="fourok_hourly_live_backfill",status="SUCCESS"} 1' in text
    assert (
        'fourok_dagster_latest_run_status{job="fourok_hourly_live_backfill",status="SUCCESS"} 1'
        in text
    )
    assert (
        "fourok_dagster_last_success_timestamp_seconds"
        '{job="fourok_hourly_live_backfill"} 1781028065' in text
    )
    assert 'fourok_dagster_schedule_running{name="fourok_hourly_live_backfill_schedule"} 1' in text
    assert (
        'fourok_dagster_step_duration_seconds{job="fourok_hourly_live_backfill",'
        'status="SUCCESS",step="meltano_slack_live_raw_landing"} 10' in text
    )
    assert (
        'fourok_dagster_step_failures_total{job="fourok_hourly_live_backfill",'
        'step="fourok_retrieval_records"} 1' in text
    )
    assert (
        'fourok_dagster_latest_run_stage_status{job="fourok_hourly_live_backfill",'
        'stage="meltano_slack_live_raw_landing",status="SUCCESS"} 1' in text
    )
    assert (
        'fourok_dagster_latest_run_stage_status{job="fourok_hourly_live_backfill",'
        'stage="fourok_retrieval_records",status="FAILURE"} 1' in text
    )
    assert 'fourok_source_records_total{record_type="message",source_system="slack"} 2' in text
    assert (
        'fourok_source_records_total{record_type="organization",source_system="twenty"} 1' in text
    )
    assert (
        'fourok_google_drive_files_total{content_status="metadata_only",'
        'export_status="unsupported_mime_type",mime_type="image/png"} 1' in text
    )
    assert (
        'fourok_raw_landed_records_total{source_system="slack",stream="slack_messages"} 2' in text
    )
    assert 'fourok_canonical_objects_total{object_type="company"} 2' in text
    assert 'fourok_entity_links_total{relationship="mentions"} 1' in text
    assert (
        'fourok_source_latest_record_timestamp_seconds{source_system="linear"} 1781032530' in text
    )
    assert 'fourok_source_latest_record_timestamp_seconds{source_system="slack"} 1781033100' in text
    assert (
        'fourok_source_latest_record_timestamp_seconds{source_system="twenty"} 1780063291' in text
    )
    assert 'fourok_retrieval_records_total{status="current"} 2' in text
    assert 'fourok_embedding_records_total{status="embedded"} 1' in text
    assert 'fourok_embedding_records_total{status="missing"} 1' in text
    assert "fourok_embedding_coverage_ratio 0.5" in text
    assert (
        'fourok_embedding_index_duration_seconds{job="fourok_hourly_live_backfill",'
        'status="FAILURE"} 10' in text
    )
    assert (
        'fourok_retrieval_requests_total{retriever_set="keyword,vector",status="succeeded"} 1'
        in text
    )
    assert 'fourok_retrieval_requests_total{retriever_set="keyword",status="succeeded"} 1' in text
    assert 'fourok_retrieval_requests_total{retriever_set="vector",status="failed"} 1' in text
    assert 'fourok_retrieval_zero_result_requests_total{retriever_set="keyword"} 1' in text
    assert 'fourok_retrieval_pre_rerank_candidates_sum{retriever_set="keyword,vector"} 17' in text
    assert 'fourok_retrieval_distinct_sources_sum{retriever_set="keyword,vector"} 13' in text
    assert 'fourok_retrieval_returned_results_sum{retriever_set="keyword,vector"} 5' in text
    assert (
        'fourok_retrieval_duration_ms_sum{retriever_set="keyword,vector",status="succeeded"} '
        "42.5" in text
    )
    assert 'fourok_webhook_events_total{source_system="linear",status="pending"} 1' in text
    assert 'fourok_connector_job_runs_total{connector="linear",status="failed"} 1' in text
    assert 'fourok_connector_latest_run_status{connector="linear",status="failed"} 1' in text
    assert 'fourok_connector_latest_run_status{connector="slack",status="success"} 1' in text
    assert (
        'fourok_connector_latest_finished_timestamp_seconds{connector="linear"} 1781031780' in text
    )
    assert 'fourok_dagster_repository_discovery_status{status="ok"} 1' in text


def test_metrics_exporter_discovers_fourok_repo_from_multiple_graphql_nodes(tmp_path: Path) -> None:
    def fake_graphql(_url: str, _query: str, _variables=None):
        return {
            "data": {
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [
                        {
                            "name": "other_repository",
                            "schedules": [],
                            "sensors": [],
                        },
                        {
                            "name": "__repository__",
                            "location": {"name": "fourok_pipeline"},
                            "pipelines": [{"name": "fourok_hourly_live_backfill"}],
                            "schedules": [
                                {
                                    "name": "fourok_hourly_live_backfill_schedule",
                                    "scheduleState": {"status": "RUNNING"},
                                }
                            ],
                            "sensors": [
                                {
                                    "name": "fourok_webhook_backlog_sensor",
                                    "sensorState": {"status": "RUNNING"},
                                }
                            ],
                        },
                    ],
                },
                "runsOrError": {"__typename": "Runs", "results": []},
            }
        }

    metrics = collect_runtime_metrics(
        dagster_url="http://dagster.example/graphql",
        state_path=tmp_path / "unused.sqlite",
        graphql=fake_graphql,
    )
    text_metrics = render_prometheus_metrics(metrics)

    assert (
        'fourok_dagster_schedule_running{name="fourok_hourly_live_backfill_schedule"} 1'
        in text_metrics
    )
    assert 'fourok_dagster_sensor_running{name="fourok_webhook_backlog_sensor"} 1' in text_metrics
    assert 'fourok_dagster_repository_discovery_status{status="ok"} 1' in text_metrics


def test_metrics_exporter_reports_discovery_error_when_no_repositories(tmp_path: Path) -> None:
    def fake_graphql(_url: str, _query: str, _variables=None):
        return {
            "data": {
                "repositoriesOrError": {"__typename": "RepositoryConnection", "nodes": []},
                "runsOrError": {"__typename": "Runs", "results": []},
            }
        }

    metrics = collect_runtime_metrics(
        dagster_url="http://dagster.example/graphql",
        state_path=tmp_path / "unused.sqlite",
        graphql=fake_graphql,
    )
    text_metrics = render_prometheus_metrics(metrics)

    assert 'fourok_dagster_repository_discovery_status{status="missing"} 1' in text_metrics


def test_metrics_exporter_sql_database_url_uses_mapping_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                create table source_records (
                  source_ref text primary key,
                  source_system text not null,
                  record_type text not null,
                  updated_at text not null,
                  lifecycle_state text not null,
                  metadata_json text not null default '{}'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                insert into source_records values
                  ('drive:image-1', 'google_drive', 'document',
                   '2026-06-09T19:20:00+00:00', 'active', :metadata_json)
                """
            ),
            {
                "metadata_json": (
                    '{"mime_type": "image/png", "content_status": "metadata_only", '
                    '"export_status": "unsupported_mime_type"}'
                )
            },
        )
        connection.execute(
            text(
                """
                create table connector_job_runs (
                  job_id text primary key,
                  connector_name text not null,
                  status text not null,
                  started_at text not null,
                  finished_at text not null
                )
                """
            )
        )
        connection.execute(
            text(
                """
                insert into connector_job_runs values
                  ('job-1', 'slack', 'success',
                   '2026-06-09T19:00:00+00:00', '2026-06-09T19:01:00+00:00')
                """
            )
        )

    def fake_graphql(_url: str, _query: str, _variables=None):
        return {
            "data": {
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [{"schedules": [], "sensors": []}],
                },
                "runsOrError": {"__typename": "Runs", "results": []},
            }
        }

    metrics = collect_runtime_metrics(
        dagster_url="http://dagster.example/graphql",
        state_path=tmp_path / "unused.sqlite",
        database_url=f"sqlite:///{db_path}",
        graphql=fake_graphql,
    )
    text_metrics = render_prometheus_metrics(metrics)

    assert (
        'fourok_google_drive_files_total{content_status="metadata_only",'
        'export_status="unsupported_mime_type",mime_type="image/png"} 1' in text_metrics
    )
    assert (
        'fourok_connector_latest_run_status{connector="slack",status="success"} 1' in text_metrics
    )
    assert (
        'fourok_connector_latest_finished_timestamp_seconds{connector="slack"} 1781031660'
        in text_metrics
    )
