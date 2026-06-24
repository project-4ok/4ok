import ast
import json
import re
from pathlib import Path


def test_compose_declares_app_context_cli_runtime() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    app_service = _compose_service_block(compose, "app")

    assert "  app:" in compose
    assert "4ok-app:${FOUR_OK_IMAGE_TAG:?set FOUR_OK_IMAGE_TAG}" in compose
    assert "docker/app.Dockerfile" in compose
    assert "FOUR_OK_DATABASE_URL: ${FOUR_OK_DATABASE_URL:?set FOUR_OK_DATABASE_URL}" in app_service
    assert (
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}"
        in _compose_service_block(compose, "postgres")
    )
    assert "HONCHO_URL" not in app_service
    assert "HONCHO_SYNC_SOURCES" not in app_service
    assert "honcho:" not in app_service
    assert '"honcho-sync"' not in app_service
    assert '"runtime-monitor"' in app_service
    assert '"health"' in app_service
    assert "FOUR_OK_OBSERVABILITY_ENABLED" in app_service
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in app_service
    assert "http://observability:4318" in app_service
    assert "fourok-local:/app/.local" in app_service
    assert "fourok-data:/var/lib/fourok" in app_service
    assert "${FOUR_OK_CONFIG_PATH:-./.local/fourok.toml}:/etc/fourok/fourok.toml:ro" in app_service


def test_compose_does_not_use_latest_image_tags() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert ":latest" not in compose


def test_compose_active_services_have_restart_policies() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service_name in ["postgres", "observability", "app"]:
        assert "restart: unless-stopped" in _compose_service_block(compose, service_name)


def test_compose_active_services_have_health_checks() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service_name in ["postgres", "observability", "app"]:
        assert "healthcheck:" in _compose_service_block(compose, service_name)

    app_service = _compose_service_block(compose, "app")
    assert '"/app/.venv/bin/fourok health --database-url \\\"$$FOUR_OK_DATABASE_URL\\\""' in app_service
    assert '"--config"' not in _compose_healthcheck_block(app_service)


def test_compose_app_command_is_long_running_when_restart_policy_is_enabled() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    app_service = _compose_service_block(compose, "app")

    assert "restart: unless-stopped" in app_service
    assert "command:" in app_service
    assert '"runtime-monitor"' in app_service
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
    assert '"127.0.0.1:3000:3000"' in observability_service
    assert '"127.0.0.1:3100:3100"' in observability_service
    assert '"127.0.0.1:3200:3200"' in observability_service
    assert '"127.0.0.1:4317:4317"' in observability_service
    assert '"127.0.0.1:4318:4318"' in observability_service


def test_app_image_runs_installed_cli_without_runtime_uv_sync() -> None:
    dockerfile = Path("docker/app.Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("# syntax=docker/dockerfile:")
    assert "apt.postgresql.org" in dockerfile
    assert "postgresql-client-16" in dockerfile
    assert "--mount=type=cache,target=/root/.cache/uv" in dockerfile
    assert "COPY pyproject.toml uv.lock README.md docker-compose.yml ./" in dockerfile
    assert "uv sync --frozen --no-group dev --no-install-project" in dockerfile
    assert "COPY src ./src" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/fourok"]' in dockerfile
    assert 'ENTRYPOINT ["uv", "run", "fourok"]' not in dockerfile


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
    assert "docker/docling-worker.Dockerfile" not in compose
    assert "docker/graphiti-runner.Dockerfile" not in compose
    assert 'profiles: ["experiments"]' not in compose


def test_compose_declares_local_observability_profile() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    observability_service = _compose_service_block(compose, "observability")

    assert "  observability:" in compose
    assert 'profiles: ["observability"]' in observability_service
    assert "image: grafana/otel-lgtm:0.28.0" in observability_service
    assert '"127.0.0.1:3000:3000"' in observability_service
    assert '"127.0.0.1:3100:3100"' in observability_service
    assert '"127.0.0.1:3200:3200"' in observability_service
    assert '"127.0.0.1:4317:4317"' in observability_service
    assert '"127.0.0.1:4318:4318"' in observability_service
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

    assert 'profiles: ["observability"]' in promtail_service
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
    dashboard = Path("deploy/observability/fourok-local-runtime-logs.json").read_text(encoding="utf-8")

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

    assert "4ok dashboard" in dashboard_provider
    assert "fourok-local-runtime-logs.json" in dashboard_provider
    assert dashboard_data["title"] == "4ok dashboard"
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
    assert any(
        "fourok_connector_latest_finished_timestamp_seconds" in expr for expr in prometheus_exprs
    )
    assert any(
        'fourok_connector_latest_finished_timestamp_seconds{connector!~".*(fixture|gmail[-_]singer).*"}'
        in expr
        for expr in prometheus_exprs
    )
    assert any("fourok_dagster_latest_run_stage_status" in expr for expr in prometheus_exprs)
    assert any(
        "fourok_dagster_latest_run_stage_status" in expr and "clamp_max" in expr
        for expr in prometheus_exprs
    )
    assert any(
        'fourok_dagster_latest_run_stage_status{exported_job="$dagster_job",status!="SUCCESS"}' in expr
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
    assert any("otelcol_receiver_accepted_spans_total" in expr for expr in prometheus_exprs)
    panel_titles = {panel["title"] for panel in prometheus_panels}
    assert "[Logs] Last 5 4ok Docker logs" in {panel["title"] for panel in dashboard_data["panels"]}
    dashboard_titles = {panel["title"] for panel in dashboard_data["panels"]}
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
        "[Logs] Last 5 4ok Docker logs",
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
    positions = {panel["title"]: panel["gridPos"]["y"] for panel in dashboard_data["panels"]}
    non_success_title = "[Pipeline] Non-success Dagster stages (latest run)"
    assert positions["[Pipeline] Dagster lineage health map"] == 0
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
        panel for panel in tempo_panels if panel["title"] == "[Tracing] Recent 4OK traces (Tempo)"
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

    assert 'profiles: ["observability"]' in service
    assert "image: 4ok-app:${FOUR_OK_IMAGE_TAG:?set FOUR_OK_IMAGE_TAG}" in service
    assert 'entrypoint: ["/app/.venv/bin/python"]' in service
    assert '"-m"' in service
    assert '"fourok.runtime.metrics_exporter"' in service
    assert '"9108"' in service
    assert "FOUR_OK_DAGSTER_GRAPHQL_URL: http://dagster-webserver:3001/graphql" in service
    assert "FOUR_OK_DATABASE_URL: ${FOUR_OK_DATABASE_URL:?set FOUR_OK_DATABASE_URL}" in service
    assert "fourok-local:/app/.local" in service
    assert "fourok-metrics-exporter:9108" in prometheus
    assert "fourok-dagster-runtime" in prometheus


def test_compose_declares_dagster_pipeline_profile() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service_name in [
        "dagster-postgres",
        "dagster-code",
        "dagster-webserver",
        "dagster-daemon",
    ]:
        service = _compose_service_block(compose, service_name)
        assert 'profiles: ["pipeline"]' in service
        assert "restart: unless-stopped" in service
        assert "healthcheck:" in service

    public_dagster_runtime_image = (
        "docker.io/dagster/dagster-k8s:1.13.8@"
        "sha256:24661edd6c98705eba61823804afab65ecd4691bf74a697b7c0d0659df5ed301"
    )
    assert f"${{FOUR_OK_DAGSTER_RUNTIME_IMAGE:-{public_dagster_runtime_image}}}" in compose
    assert "4ok-dagster-code:${FOUR_OK_IMAGE_TAG:?set FOUR_OK_IMAGE_TAG}" in compose
    assert "docker/dagster.Dockerfile" in compose
    assert "target: dagster-code" in _compose_service_block(compose, "dagster-code")
    assert "target: dagster-runtime" not in _compose_service_block(compose, "dagster-webserver")
    assert "target: dagster-runtime" not in _compose_service_block(compose, "dagster-daemon")
    assert "./deploy/dagster/dagster.yaml:/tmp/fourok-dagster-home/dagster.yaml:ro" in compose
    assert "./deploy/dagster/workspace.yaml:/tmp/fourok-dagster-home/workspace.yaml:ro" in compose
    assert '"127.0.0.1:3001:3001"' in _compose_service_block(compose, "dagster-webserver")
    for service_name, service_name_env in [
        ("dagster-code", "fourok-dagster-code"),
        ("dagster-webserver", "fourok-dagster-webserver"),
        ("dagster-daemon", "fourok-dagster-daemon"),
    ]:
        service = _compose_service_block(compose, service_name)
        assert "FOUR_OK_OBSERVABILITY_ENABLED: ${FOUR_OK_OBSERVABILITY_ENABLED:-true}" in service
        assert (
            "OTEL_EXPORTER_OTLP_ENDPOINT: "
            "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://observability:4318}" in service
        )
        assert f"OTEL_SERVICE_NAME: ${{OTEL_SERVICE_NAME:-{service_name_env}}}" in service
    assert "dagster-postgres-data:/var/lib/postgresql/data" in compose
    assert "dagster-local:/var/lib/dagster" in compose


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
