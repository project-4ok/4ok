import ast
import json
import re
from pathlib import Path


def test_compose_declares_app_context_cli_runtime() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    app_service = _compose_service_block(compose, "app")

    assert compose.startswith("name: fourok\n")
    assert "  app:" in compose
    assert "fourok-app:${FOUROK_IMAGE_TAG:-local-check}" in compose
    assert "deploy/docker/app.Dockerfile" in compose
    assert "FOUROK_DATABASE_URL: ${FOUROK_DATABASE_URL:-" in app_service
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-local-check}" in _compose_service_block(
        compose, "postgres"
    )
    assert "HONCHO_URL" not in app_service
    assert "HONCHO_SYNC_SOURCES" not in app_service
    assert "honcho:" not in app_service
    assert "cerbos:" not in app_service
    assert '"honcho-sync"' not in app_service
    assert '"runtime-monitor"' in app_service
    assert '"/app/.venv/bin/fourok", "health", "--database-only"' in app_service
    assert "FOUROK_OBSERVABILITY_ENABLED" in app_service
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in app_service
    assert "http://observability:4318" in app_service
    assert "fourok-local:/app/.local" in app_service
    assert "fourok-data:/var/lib/fourok" in app_service
    assert "${FOUROK_CONFIG_PATH:-./.local/fourok.toml}:/etc/fourok/fourok.toml:ro" in app_service


def test_compose_does_not_use_latest_image_tags() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert ":latest" not in compose


def test_compose_active_services_have_restart_policies() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service_name in ["postgres", "observability", "app", "mcp"]:
        assert "restart: unless-stopped" in _compose_service_block(compose, service_name)


def test_compose_active_services_have_health_checks() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service_name in ["postgres", "observability", "app", "mcp"]:
        assert "healthcheck:" in _compose_service_block(compose, service_name)

    app_service = _compose_service_block(compose, "app")
    healthcheck = _compose_healthcheck_block(app_service)

    assert '["CMD", "/app/.venv/bin/fourok", "health", "--database-only"]' in healthcheck
    assert '"--config"' not in healthcheck
    assert '"--database-url"' not in healthcheck


def test_compose_app_command_is_long_running_when_restart_policy_is_enabled() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    app_service = _compose_service_block(compose, "app")

    assert "restart: unless-stopped" in app_service
    assert "command:" in app_service
    assert '"runtime-monitor"' in app_service
    assert '"--database-only"' in app_service
    assert not re.search(
        r"command:\s*\[\s*\"health\",\s*\"--config\",\s*\"/etc/fourok/fourok\.toml\",\s*\]",
        app_service,
        flags=re.MULTILINE,
    )


def test_compose_active_services_use_named_persistent_volumes() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres-data:/var/lib/postgresql/data" in _compose_service_block(compose, "postgres")
    assert "observability-data:/data" in _compose_service_block(compose, "observability")
    assert "fourok-local:/app/.local" in _compose_service_block(compose, "app")
    assert "fourok-data:/var/lib/fourok" in _compose_service_block(compose, "app")
    assert "\nvolumes:\n" in compose
    assert "  postgres-data:\n" in compose
    assert "  observability-data:\n" in compose
    assert "  fourok-local:\n" in compose
    assert "  fourok-data:\n" in compose


def test_compose_active_services_bind_host_ports_to_loopback_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:5432:5432"' in _compose_service_block(compose, "postgres")
    observability_service = _compose_service_block(compose, "observability")
    assert '"127.0.0.1:${FOUROK_GRAFANA_PORT:-3000}:3000"' in observability_service
    assert '"127.0.0.1:${FOUROK_LOKI_PORT:-3100}:3100"' in observability_service
    assert '"127.0.0.1:${FOUROK_TEMPO_PORT:-3200}:3200"' in observability_service
    assert '"127.0.0.1:${FOUROK_OTLP_GRPC_PORT:-4317}:4317"' in observability_service
    assert '"127.0.0.1:${FOUROK_OTLP_HTTP_PORT:-4318}:4318"' in observability_service
    assert '"127.0.0.1:${FOUROK_DAGSTER_PORT:-3001}:3001"' in _compose_service_block(
        compose, "dagster-webserver"
    )
    assert '"127.0.0.1:${FOUROK_MCP_PORT:-8010}:8010"' in _compose_service_block(compose, "mcp")


def test_installer_chooses_free_local_ports_for_onboarding() -> None:
    installer = Path("install.sh").read_text(encoding="utf-8")

    assert "choose_host_port FOUROK_GRAFANA_PORT 3000" in installer
    assert "choose_host_port FOUROK_DAGSTER_PORT 3001" in installer
    assert "choose_host_port FOUROK_MCP_PORT 8010" in installer
    assert "Port $preferred_port is busy" in installer
    assert "FOUROK_RESERVED_HOST_PORTS" in installer
    assert 'while port_reserved "$port" || ! port_available "$port"' in installer


def test_installer_installs_plain_cli_shims() -> None:
    installer = Path("install.sh").read_text(encoding="utf-8")

    assert "install_cli_shims()" in installer
    assert 'local bin_dir="$HOME/.local/bin"' in installer
    assert "for command in fourok fourok-dev fourok-mcp" in installer
    assert 'exec uv --project "$project_dir" run $command "\\$@"' in installer
    assert "install_cli_shims" in installer.split("uv sync", maxsplit=1)[1]
    assert "Next:    fourok onboard" in installer
    assert "Status:  fourok status" in installer
    assert "fourok onboard connectors" not in installer
    assert "Next:    uv run fourok onboard" not in installer


def test_installer_defaults_repo_url_to_4ok_repository() -> None:
    installer = Path("install.sh").read_text(encoding="utf-8")

    assert 'REPO_URL="${FOUROK_REPO_URL:-https://github.com/project-4ok/4ok.git}"' in installer


def test_installer_fails_early_when_docker_daemon_is_unreachable() -> None:
    installer = Path("install.sh").read_text(encoding="utf-8")

    assert '[ "$START_STACK" != "0" ] && ! docker info >/dev/null 2>&1' in installer
    assert "Docker daemon is not reachable" in installer


def test_installer_does_not_seed_demo_context_by_default() -> None:
    installer = Path("install.sh").read_text(encoding="utf-8")
    startup_tail = installer.split("start_local_stack", maxsplit=1)[1]

    assert "seed_fixture_data" not in installer
    assert "tests/fixtures/emails" not in installer
    assert "fourok search" not in startup_tail
    assert "refund cancellation payment" not in installer


def test_compose_starts_streamable_http_mcp_service_by_default() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    mcp_service = _compose_service_block(compose, "mcp")

    assert "  mcp:" in compose
    assert "profiles:" not in mcp_service
    assert "fourok-app:${FOUROK_IMAGE_TAG:-local-check}" in mcp_service
    assert 'entrypoint: ["/app/.venv/bin/fourok-mcp"]' in mcp_service
    assert '"--transport"' in mcp_service
    assert '"streamable-http"' in mcp_service
    assert '"--host"' in mcp_service
    assert '"0.0.0.0"' in mcp_service
    assert '"--port"' in mcp_service
    assert '"8010"' in mcp_service
    assert '"--mount-path"' in mcp_service
    assert '"/mcp"' in mcp_service
    assert "FOUROK_DATABASE_URL:" in mcp_service
    assert "FOUROK_CONFIG_PATH: /etc/fourok/fourok.toml" in mcp_service


def test_app_image_runs_installed_cli_without_runtime_uv_sync() -> None:
    dockerfile = Path("deploy/docker/app.Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("# syntax=docker/dockerfile:")
    assert "apt.postgresql.org" in dockerfile
    assert "postgresql-client-16" in dockerfile
    assert "--mount=type=cache,target=/root/.cache/uv" in dockerfile
    assert "COPY pyproject.toml uv.lock README.md docker-compose.yml ./" in dockerfile
    assert "uv sync --frozen --no-group dev --no-install-project" in dockerfile
    assert "COPY src ./src" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/fourok"]' in dockerfile
    assert 'ENTRYPOINT ["uv", "run", "fourok"]' not in dockerfile


def test_deployment_dockerfiles_live_under_deploy_directory() -> None:
    assert not Path("docker").exists()
    assert Path("deploy/docker/app.Dockerfile").exists()
    assert Path("deploy/docker/dagster.Dockerfile").exists()
    assert Path("deploy/docker/docling-worker.Dockerfile").exists()
    assert not Path("deploy/docker/graphiti-runner.Dockerfile").exists()


def test_dockerignore_keeps_local_artifacts_out_of_build_context() -> None:
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    assert ".local/" in dockerignore
    assert ".reference/" in dockerignore
    assert "**/__pycache__/" in dockerignore
    assert "*.sqlite" in dockerignore


def test_compose_excludes_deferred_experiment_runtimes() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "  honcho:" not in compose
    assert "  honcho-db:" not in compose
    assert "  honcho-redis:" not in compose
    assert "  graphiti-neo4j:" not in compose
    assert "  graphiti-runner:" not in compose
    assert "  docling-worker:" not in compose
    assert "context: ./.reference/graphiti" not in compose
    assert "NEO4J_URI:" not in compose
    assert "GRAPHITI_NEO4J_PASSWORD" not in compose
    assert "deploy/docker/docling-worker.Dockerfile" not in compose
    assert "deploy/docker/graphiti-runner.Dockerfile" not in compose
    assert 'profiles: ["experiments"]' not in compose


def test_compose_declares_local_observability_as_default_runtime_surface() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    observability_service = _compose_service_block(compose, "observability")

    assert "  observability:" in compose
    assert "profiles:" not in observability_service
    assert "image: grafana/otel-lgtm:0.28.0" in observability_service
    assert '"127.0.0.1:${FOUROK_GRAFANA_PORT:-3000}:3000"' in observability_service
    assert '"127.0.0.1:${FOUROK_LOKI_PORT:-3100}:3100"' in observability_service
    assert '"127.0.0.1:${FOUROK_TEMPO_PORT:-3200}:3200"' in observability_service
    assert '"127.0.0.1:${FOUROK_OTLP_GRPC_PORT:-4317}:4317"' in observability_service
    assert '"127.0.0.1:${FOUROK_OTLP_HTTP_PORT:-4318}:4318"' in observability_service
    assert "observability-data:/data" in observability_service
    assert "./deploy/observability/grafana-dashboards.yaml" in observability_service
    assert "./deploy/observability/fourok-local-runtime-logs.json" in observability_service
    assert (
        "./deploy/observability/prometheus.yaml:/otel-lgtm/prometheus.yaml:ro"
        in observability_service
    )
    assert "curl -fsS http://localhost:3000/api/health" in observability_service
    assert "wget -qO-" not in observability_service


def test_compose_declares_promtail_docker_log_aggregation() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    promtail_service = _compose_service_block(compose, "promtail")

    assert "profiles:" not in promtail_service
    assert "image: grafana/promtail:3.5.3" in promtail_service
    assert (
        "./deploy/observability/promtail-config.yml:/etc/promtail/config.yml:ro" in promtail_service
    )
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in promtail_service
    assert "/var/lib/docker/containers:/var/lib/docker/containers:ro" in promtail_service
    assert '"-config.file=/etc/promtail/config.yml"' in promtail_service
    assert "observability:" in promtail_service


def test_observability_files_define_fourok_log_dashboard_and_docker_labels() -> None:
    promtail = Path("deploy/observability/promtail-config.yml").read_text(encoding="utf-8")
    dashboard_provider = Path("deploy/observability/grafana-dashboards.yaml").read_text(
        encoding="utf-8"
    )
    dashboard = Path("deploy/observability/fourok-local-runtime-logs.json").read_text(
        encoding="utf-8"
    )

    assert "docker_sd_configs:" in promtail
    assert "__meta_docker_container_label_com_docker_compose_service" in promtail
    assert "target_label: compose_service" in promtail
    assert "target_label: compose_project" in promtail
    assert "http://observability:3100/loki/api/v1/push" in promtail
    dashboard_data = json.loads(dashboard)
    expressions = [
        target["expr"]
        for panel in dashboard_data["panels"]
        for target in panel.get("targets", [])
        if "expr" in target
    ]

    assert "fourok dashboard" in dashboard_provider
    assert "fourok-local-runtime-logs.json" in dashboard_provider
    assert dashboard_data["title"] == "fourok dashboard"
    dashboard_titles = {panel["title"] for panel in dashboard_data["panels"]}
    assert "[Deployment] Observability data coverage" in dashboard_titles
    assert "[Deployment] Prometheus metrics present" in dashboard_titles
    assert "[Deployment] Recent fourok log streams" in dashboard_titles
    assert "[Deployment] Configured live sources" in dashboard_titles
    assert "[Deployment] Retrieval telemetry present" in dashboard_titles
    assert "[Deployment] Embedding coverage complete" in dashboard_titles
    assert '{compose_project=~"$compose_project"}' in expressions
    assert '{compose_service=~"$compose_service"}' in expressions
    assert '{compose_service=~"$compose_service"} |= "STEP_FAILURE"' in expressions
    prometheus_panels = [
        panel
        for panel in dashboard_data["panels"]
        if panel.get("datasource", {}).get("uid") == "prometheus"
    ]
    tempo_panels = [
        panel
        for panel in dashboard_data["panels"]
        if panel.get("datasource", {}).get("uid") == "tempo"
    ]
    prometheus_exprs = [
        target["expr"]
        for panel in prometheus_panels
        for target in panel.get("targets", [])
        if "expr" in target
    ]

    assert any("fourok_dagster_last_success_timestamp_seconds" in expr for expr in prometheus_exprs)
    assert any("fourok_connector_latest_run_status" in expr for expr in prometheus_exprs)
    configured_sources_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Deployment] Configured live sources"
    )
    assert configured_sources_panel["targets"][0]["expr"] == (
        'sum(fourok_connector_latest_run_status{status=~"success|succeeded"}) or vector(0)'
    )
    assert "0 configured" in json.dumps(configured_sources_panel)
    assert "visible error" in configured_sources_panel["description"]
    assert [
        step["value"]
        for step in configured_sources_panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    ] == [None, 1]
    assert any(
        "fourok_connector_latest_finished_timestamp_seconds" in expr for expr in prometheus_exprs
    )
    assert any(
        'fourok_connector_latest_finished_timestamp_seconds{connector!~".*(fixture|gmail[-_]singer).*"}'
        in expr
        for expr in prometheus_exprs
    )
    assert any("fourok_dagster_latest_run_stage_status" in expr for expr in prometheus_exprs)
    lineage_titles = {
        "① Raw landing",
        "② Source records",
        "③ Retrieval records",
        "④ Operator dashboard",
        "⑤ Audit metadata",
        "↳ Entity links",
    }
    lineage_panels = [panel for panel in prometheus_panels if panel["title"] in lineage_titles]
    assert lineage_panels
    for panel in lineage_panels:
        expr = panel["targets"][0]["expr"]
        assert "fourok_dagster_latest_run_stage_status" in expr
        assert "clamp_max" not in expr
        assert "total number of latest-run FAILURE stages" in panel["description"]
        assert 'status="FAILURE"' in expr
    raw_landing_panel = next(panel for panel in lineage_panels if panel["title"] == "① Raw landing")
    assert 'stage!~"fourok_.*source_records.*"' in raw_landing_panel["targets"][0]["expr"]
    assert "1+ failures" not in dashboard
    assert any(
        'fourok_dagster_latest_run_stage_status{exported_job="$dagster_job",status!="SUCCESS"}'
        in expr
        for expr in prometheus_exprs
    )
    non_success_panel = next(
        panel
        for panel in dashboard_data["panels"]
        if panel["title"] == "[Pipeline] Non-success Dagster stages (latest run)"
    )
    assert non_success_panel["type"] == "table"
    assert non_success_panel["targets"][0].get("instant") is True
    assert any("fourok_source_latest_record_timestamp_seconds" in expr for expr in prometheus_exprs)
    assert any("fourok_source_records_total" in expr for expr in prometheus_exprs)
    assert any("fourok_raw_landed_records_total" in expr for expr in prometheus_exprs)
    assert any("fourok_canonical_objects_total" in expr for expr in prometheus_exprs)
    assert any("fourok_entity_links_total" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_records_total" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_requests_total" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_pre_rerank_candidates_sum" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_zero_result_requests_total" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_duration_ms_sum" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_source_inspection_rank_total" in expr for expr in prometheus_exprs)
    assert any("fourok_retrieval_source_inspection_rank_sum" in expr for expr in prometheus_exprs)
    assert any("otelcol_receiver_accepted_spans_total" in expr for expr in prometheus_exprs)
    panel_titles = {panel["title"] for panel in prometheus_panels}
    embedding_deployment_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Deployment] Embedding coverage complete"
    )
    assert embedding_deployment_panel["targets"][0]["expr"] == "fourok_embedding_coverage_ratio"
    assert "fourok_embedding_records_total" not in embedding_deployment_panel["targets"][0]["expr"]
    assert "[Logs] Last 5 fourok Docker logs" in {
        panel["title"] for panel in dashboard_data["panels"]
    }
    assert "[Logs] Last 5 Dagster code logs" in dashboard_titles
    assert "[Logs] Last 5 Dagster failures" in dashboard_titles
    assert "[Logs] Latest 5 runtime errors by service" in {
        panel["title"] for panel in dashboard_data["panels"]
    }
    assert "[Logs] Runtime log activity by service (15m rolling count)" in {
        panel["title"] for panel in dashboard_data["panels"]
    }
    runtime_activity_panel = next(
        panel
        for panel in dashboard_data["panels"]
        if panel["title"] == "[Logs] Runtime log activity by service (15m rolling count)"
    )
    assert (
        'count_over_time({compose_project=~"$compose_project"}[15m])'
        in runtime_activity_panel["targets"][0]["expr"]
    )
    assert "log activity, not container health" in runtime_activity_panel["description"]
    for panel_title in [
        "[Logs] Last 5 fourok Docker logs",
        "[Logs] Last 5 Dagster code logs",
        "[Logs] Last 5 Dagster failures",
        "[Logs] Latest 5 runtime errors by service",
    ]:
        panel = next(panel for panel in dashboard_data["panels"] if panel["title"] == panel_title)
        assert panel["type"] == "logs"
        assert any(target.get("maxLines") == 5 for target in panel.get("targets", []))
    assert "[Pipeline] Dagster lineage health map" in dashboard_titles
    for title in [
        "① Raw landing",
        "② Source records",
        "③ Retrieval records",
        "④ Operator dashboard",
        "⑤ Audit metadata",
        "↳ Entity links",
    ]:
        assert title in panel_titles
    assert "[Pipeline] Latest live connector run status" in panel_titles
    assert "[Pipeline] Live connector freshness age (minutes)" in panel_titles
    connector_freshness_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Pipeline] Live connector freshness age (minutes)"
    )
    assert connector_freshness_panel["fieldConfig"]["defaults"]["unit"] == "m"
    assert [
        step["value"]
        for step in connector_freshness_panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    ] == [None, 65, 120]
    source_freshness_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Pipeline] Source freshness age by connector (minutes)"
    )
    assert source_freshness_panel["targets"][0]["legendFormat"] == "{{source_system}}"
    assert source_freshness_panel["fieldConfig"]["defaults"]["unit"] == "m"
    assert [
        step["value"]
        for step in source_freshness_panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    ] == [None, 10080, 20160]
    assert "data freshness" in source_freshness_panel["description"]
    assert "connector-run completion" in source_freshness_panel["description"]
    assert "[Pipeline] Non-success Dagster stages (latest run)" in panel_titles
    assert "[Pipeline] Dagster step failures" not in panel_titles
    step_duration_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Pipeline] Dagster step duration seconds"
    )
    assert step_duration_panel["gridPos"]["w"] == 24
    assert "[Metrics] Imported source records by source/type" in panel_titles
    assert "[Metrics] Processed canonical objects by type" in panel_titles
    assert "[Metrics] Canonical object type ratio" in panel_titles
    canonical_ratio_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Metrics] Canonical object type ratio"
    )
    assert canonical_ratio_panel["type"] == "piechart"
    assert canonical_ratio_panel["targets"][0]["expr"] == "fourok_canonical_objects_total"
    assert "[Metrics] Processed entity links by relationship" in panel_titles
    assert "[Metrics] Raw landed records by connector/stream" in panel_titles
    for title in [
        "[Retrieval] Requests by status/retriever",
        "[Retrieval] Candidates found before reranking",
        "[Retrieval] Zero-result requests",
        "[Retrieval] Average duration (ms)",
        "[Retrieval] Opened source rank distribution",
        "[Retrieval] Average opened source rank",
    ]:
        assert title in panel_titles
    for title in [
        "[Embedding] Coverage ratio",
        "[Embedding] Missing retrieval units",
        "[Embedding] Latest indexing duration seconds",
    ]:
        assert title in panel_titles
    assert any("fourok_embedding_coverage_ratio" in expr for expr in prometheus_exprs)
    assert any("fourok_embedding_records_total" in expr for expr in prometheus_exprs)
    assert any("fourok_embedding_index_duration_seconds" in expr for expr in prometheus_exprs)
    retrieval_candidates_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Retrieval] Candidates found before reranking"
    )
    assert "before reranking" in retrieval_candidates_panel["description"]
    inspected_rank_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Retrieval] Opened source rank distribution"
    )
    assert inspected_rank_panel["type"] == "bargauge"
    assert inspected_rank_panel["gridPos"] == {"x": 0, "y": 88, "w": 12, "h": 7}
    assert inspected_rank_panel["targets"][0]["expr"] == (
        "sum by (rank) (fourok_retrieval_source_inspection_rank_total)"
    )
    assert inspected_rank_panel["targets"][0]["instant"] is True
    assert "agent chose to open" in inspected_rank_panel["description"]
    average_opened_rank_panel = next(
        panel
        for panel in prometheus_panels
        if panel["title"] == "[Retrieval] Average opened source rank"
    )
    assert average_opened_rank_panel["type"] == "stat"
    assert average_opened_rank_panel["gridPos"] == {"x": 12, "y": 88, "w": 12, "h": 7}
    assert average_opened_rank_panel["targets"][0]["instant"] is True
    assert (
        "fourok_retrieval_source_inspection_rank_sum"
        in average_opened_rank_panel["targets"][0]["expr"]
    )
    assert "fourok_retrieval_source_inspection_rank_total" in average_opened_rank_panel[
        "targets"
    ][0]["expr"]
    assert "agent opened via inspect_source" in average_opened_rank_panel["description"]
    positions = {panel["title"]: panel["gridPos"]["y"] for panel in dashboard_data["panels"]}
    non_success_title = "[Pipeline] Non-success Dagster stages (latest run)"
    assert "[Pipeline] Dagster lineage health map" in positions
    assert positions["① Raw landing"] < positions[non_success_title]
    assert positions["⑤ Audit metadata"] < positions[non_success_title]
    assert (
        positions[non_success_title] < positions["[Metrics] Raw landed records by connector/stream"]
    )
    assert (
        positions["[Pipeline] Minutes since successful hourly backfill"]
        < positions["[Metrics] Processed canonical objects by type"]
    )
    assert (
        positions["[Metrics] Processed canonical objects by type"]
        < positions["[Logs] Latest 5 runtime errors by service"]
    )
    assert (
        positions["[Retrieval] Requests by status/retriever"]
        < positions["[Logs] Latest 5 runtime errors by service"]
    )
    trace_panel = next(
        panel
        for panel in tempo_panels
        if panel["title"] == "[Tracing] Recent fourok traces (Tempo)"
    )
    assert trace_panel["type"] == "table"
    assert trace_panel["targets"][0]["query"] == '{ name =~ "fourok.*|meltano.*" }'
    assert trace_panel["targets"][0]["limit"] == 20
    assert any(
        panel["title"] == "[Logs] Latest 5 runtime errors by service"
        and any('|= "ERROR"' in target.get("expr", "") for target in panel.get("targets", []))
        for panel in dashboard_data["panels"]
    )
    variables = {
        var.get("name"): var for var in dashboard_data.get("templating", {}).get("list", [])
    }
    for variable in {"compose_project", "compose_service", "dagster_job"}:
        assert variable in variables
    compose_service_var = variables["compose_service"]
    assert compose_service_var.get("allValue") == ".+"
    assert compose_service_var.get("current", {}).get("value") == ".+"
    assert any(
        option.get("value") == ".+" and option.get("text") == "All"
        for option in compose_service_var.get("options", [])
    )
    assert tempo_panels


def test_compose_declares_fourok_metrics_exporter_for_prometheus() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = _compose_service_block(compose, "fourok-metrics-exporter")
    prometheus = Path("deploy/observability/prometheus.yaml").read_text(encoding="utf-8")

    assert "profiles:" not in service
    assert "image: fourok-app:${FOUROK_IMAGE_TAG:-local-check}" in service
    assert 'entrypoint: ["/app/.venv/bin/python"]' in service
    assert '"-m"' in service
    assert '"fourok.runtime.metrics_exporter"' in service
    assert '"9108"' in service
    assert "FOUROK_DAGSTER_GRAPHQL_URL: http://dagster-webserver:3001/graphql" in service
    assert "FOUROK_DATABASE_URL: ${FOUROK_DATABASE_URL:-" in service
    assert "fourok-local:/app/.local" in service
    assert "fourok-metrics-exporter:9108" in prometheus
    assert "fourok-dagster-runtime" in prometheus


def test_installer_starts_full_observability_surface_by_default() -> None:
    installer = Path("install.sh").read_text(encoding="utf-8")
    start_stack = installer.split("start_local_stack() {", maxsplit=1)[1].split("}\\n", maxsplit=1)[
        0
    ]

    assert "--profile observability" not in start_stack
    assert "observability" in start_stack
    assert "promtail" in start_stack
    assert "fourok-metrics-exporter" in start_stack
    assert "Starting local runtime, observability, and pipeline containers" in installer


def test_compose_starts_dagster_pipeline_by_default() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service_name in [
        "dagster-postgres",
        "dagster-code",
        "dagster-webserver",
        "dagster-daemon",
    ]:
        service = _compose_service_block(compose, service_name)
        assert "profiles:" not in service
        assert "restart: unless-stopped" in service
        assert "healthcheck:" in service

    public_dagster_runtime_image = (
        "docker.io/dagster/dagster-k8s:1.13.8@"
        "sha256:24661edd6c98705eba61823804afab65ecd4691bf74a697b7c0d0659df5ed301"
    )
    assert f"${{FOUROK_DAGSTER_RUNTIME_IMAGE:-{public_dagster_runtime_image}}}" in compose
    assert "fourok-dagster-code:${FOUROK_IMAGE_TAG:-local-check}" in compose
    assert "deploy/docker/dagster.Dockerfile" in compose
    assert "target: dagster-code" in _compose_service_block(compose, "dagster-code")
    assert "target: dagster-runtime" not in _compose_service_block(compose, "dagster-webserver")
    assert "target: dagster-runtime" not in _compose_service_block(compose, "dagster-daemon")
    assert "./deploy/dagster/dagster.yaml:/tmp/fourok-dagster-home/dagster.yaml:ro" in compose
    assert "./deploy/dagster/workspace.yaml:/tmp/fourok-dagster-home/workspace.yaml:ro" in compose
    assert '"127.0.0.1:${FOUROK_DAGSTER_PORT:-3001}:3001"' in _compose_service_block(
        compose, "dagster-webserver"
    )
    for service_name, service_name_env in [
        ("dagster-code", "fourok-dagster-code"),
        ("dagster-webserver", "fourok-dagster-webserver"),
        ("dagster-daemon", "fourok-dagster-daemon"),
    ]:
        service = _compose_service_block(compose, service_name)
        assert "FOUROK_OBSERVABILITY_ENABLED: ${FOUROK_OBSERVABILITY_ENABLED:-false}" in service
        assert (
            "OTEL_EXPORTER_OTLP_ENDPOINT: "
            "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://observability:4318}" in service
        )
        assert f"OTEL_SERVICE_NAME: ${{OTEL_SERVICE_NAME:-{service_name_env}}}" in service
    assert "dagster-postgres-data:/var/lib/postgresql/data" in compose
    assert "dagster-local:/var/lib/dagster" in compose


def test_dagster_code_receives_connector_secret_env_names() -> None:
    compose_files = [Path("docker-compose.yml"), Path("deploy/runtime/docker-compose.pinned.yml")]

    for compose_file in compose_files:
        compose = compose_file.read_text(encoding="utf-8")
        dagster_code = _compose_service_block(compose, "dagster-code")

        assert "SLACK_BOT_TOKEN: ${SLACK_BOT_TOKEN:-}" in dagster_code
        assert "LINEAR_API_KEY: ${LINEAR_API_KEY:-}" in dagster_code
        assert "FOUROK_DOTENV_PATH: /workspace/fourok/.env" in dagster_code
        expected_workspace_mount = (
            "../../:/workspace/fourok:ro"
            if compose_file.name == "docker-compose.pinned.yml"
            else "./:/workspace/fourok:ro"
        )
        assert expected_workspace_mount in dagster_code
        assert "TWENTY_API_KEY: ${TWENTY_API_KEY:-}" in dagster_code
        assert (
            "GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON: "
            "${GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON:-}" in dagster_code
        )
        assert (
            "GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN: "
            "${GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN:-}" in dagster_code
        )
        assert "GOOGLE_WORKSPACE_DRIVE_IDS: ${GOOGLE_WORKSPACE_DRIVE_IDS:-}" in dagster_code


def test_compose_defaults_to_local_hash_embeddings_without_explicit_provider() -> None:
    compose_files = [Path("docker-compose.yml"), Path("deploy/runtime/docker-compose.pinned.yml")]

    for compose_file in compose_files:
        compose = compose_file.read_text(encoding="utf-8")
        for service_name in ["dagster-code", "app"]:
            service = _compose_service_block(compose, service_name)

            assert "FOUROK_EMBEDDING_PROVIDER: ${FOUROK_EMBEDDING_PROVIDER:-hash}" in service
            assert "FOUROK_EMBEDDING_DIMENSIONS: ${FOUROK_EMBEDDING_DIMENSIONS:-}" in service
            assert "FOUROK_EMBEDDING_DIMENSIONS: ${FOUROK_EMBEDDING_DIMENSIONS:-256}" not in service


def test_dagster_daemon_starts_backfill_schedule_before_running() -> None:
    compose_files = [
        Path("docker-compose.yml"),
        Path("deploy/runtime/docker-compose.pinned.yml"),
    ]

    for compose_file in compose_files:
        compose = compose_file.read_text(encoding="utf-8")
        daemon = _compose_service_block(compose, "dagster-daemon")

        assert "dagster schedule start" in daemon
        assert "fourok_hourly_live_backfill_schedule" in daemon
        assert "exec dagster-daemon run -w" in daemon
        assert daemon.index("dagster schedule start") < daemon.index("exec dagster-daemon run")


def test_pinned_runtime_dagster_defaults_match_plain_compose() -> None:
    compose = Path("deploy/runtime/docker-compose.pinned.yml").read_text(encoding="utf-8")

    for service_name in ["observability", "promtail", "fourok-metrics-exporter"]:
        service = _compose_service_block(compose, service_name)
        assert "profiles:" not in service

    for service_name in ["dagster-code", "dagster-webserver", "dagster-daemon"]:
        service = _compose_service_block(compose, service_name)
        assert "profiles:" not in service
        assert "FOUROK_OBSERVABILITY_ENABLED: ${FOUROK_OBSERVABILITY_ENABLED:-false}" in service

    webserver = _compose_service_block(compose, "dagster-webserver")
    assert 'dagster-webserver -h 0.0.0.0 -p 3001 -w "$$DAGSTER_HOME/workspace.yaml"' in webserver


def test_dagster_definitions_configure_observability_from_env() -> None:
    definitions = Path("deploy/dagster/definitions.py").read_text(encoding="utf-8")
    tree = ast.parse(definitions)
    observability_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "fourok.observability"
        for alias in node.names
    }

    assert "configure_observability_from_env" in observability_imports
    assert "configure_observability_from_env()" in definitions


def _compose_service_block(compose: str, service_name: str) -> str:
    lines = compose.splitlines()
    start = lines.index(f"  {service_name}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z0-9_-]+:$", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def _compose_healthcheck_block(service_block: str) -> str:
    lines = service_block.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "healthcheck:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^    [A-Za-z0-9_-]+:", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])
