# fourok agent experience tools

This directory is the home for repo-local tools that help AI agents and human operators understand, debug, and maintain the current fourok/4OK deployment.

Principles:

- Grafana remains the primary observability overview for humans.
- Agent CLIs should read the same Grafana/LGTM surfaces rather than invent a second dashboard.
- CLIs should produce compact JSON, avoid secrets, and distinguish dashboard health from live data/retrieval proof.
- Debugging should layer: Docker aliveness, Grafana datasources/dashboard, Prometheus metrics, Loki logs, Tempo traces, then Dagster/DB/retrieval proof.

## Grafana access

Agents access the dashboard through the Grafana HTTP API:

```bash
uv run four-ok-agent-grafana --json
```

Default Grafana URL:

```text
http://127.0.0.1:3000
```

The CLI checks:

- Grafana `/api/health`
- dashboard search for UID `fourok-local-runtime-logs`
- datasource inventory for Prometheus, Loki, and Tempo
- selected Prometheus signals through Grafana's datasource proxy
- recent Loki streams through Grafana's datasource proxy

Use the output to decide where to drill down next. Do not claim Stage 1 or retrieval correctness from this report alone; use Dagster, DB, and retrieval checks for boundary proof.
