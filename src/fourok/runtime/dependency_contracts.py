from __future__ import annotations

from dataclasses import dataclass

REQUIRED_DIMENSIONS = (
    "auth",
    "read_write_shape",
    "idempotency",
    "metadata_support",
    "docker_runtime_shape",
    "failure_behavior",
)


@dataclass(frozen=True)
class DependencyContract:
    name: str
    category: str
    active_surface: str
    status: str
    dimensions: tuple[str, ...]
    proof_commands: tuple[str, ...]
    notes: str

    def to_dict(self) -> dict[str, object]:
        missing = tuple(
            dimension for dimension in REQUIRED_DIMENSIONS if dimension not in self.dimensions
        )
        return {
            "name": self.name,
            "category": self.category,
            "active_surface": self.active_surface,
            "status": self.status,
            "dimensions": list(self.dimensions),
            "missing_dimensions": list(missing),
            "proof_commands": list(self.proof_commands),
            "notes": self.notes,
        }


DEPENDENCY_CONTRACTS = (
    DependencyContract(
        name="docker-compose-runtime",
        category="runtime",
        active_surface="internal v0 app/postgres/observability services",
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/runtime/test_compose.py tests/runtime/test_access.py -q",
            "uv run fourok goal-audit",
            "docker compose run --rm app acceptance-proof ...",
        ),
        notes="Current proof uses commit-hash app image tags, loopback-only exposed ports, "
        "health checks, restart policies, persistent volumes, and the acceptance proof.",
    ),
    DependencyContract(
        name="postgresql",
        category="database",
        active_surface="SQLAlchemy state, search, audit, backup, restore-drill wiring",
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/storage tests/integration/test_postgres.py -q",
            "docker compose run --rm app health",
            "docker compose run --rm app acceptance-proof ...",
        ),
        notes="SQLite remains the fast local fallback; PostgreSQL is the internal-prod target.",
    ),
    DependencyContract(
        name="env-secret-loading",
        category="secrets",
        active_surface="connector/runtime credential retrieval",
        status="proved-with-fake-client",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/secrets/test_env.py -q",
            "uv run pytest tests/etl/extract/test_gmail_pilot_config.py "
            "tests/etl/extract/test_gmail_pilot_retry.py -q",
        ),
        notes="Live credentials are intentionally not required for normal tests; SDK auth, "
        "shape mapping, fallback behavior, and error handling are covered with fakes.",
    ),
    DependencyContract(
        name="singer-meltano-style-connectors",
        category="connector-boundary",
        active_surface="Singer JSONL landing and Gmail SourceRecord adaptation",
        status="proved-with-fixtures",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/etl/extract/test_connectors_ingest.py "
            "tests/etl/extract/test_connectors_lifecycle.py "
            "tests/etl/extract/test_gmail_singer.py -q",
            "uv run pytest tests/test_cli_search_import.py::test_cli_lands_singer_records "
            "tests/test_cli_search_import.py::test_cli_ingests_gmail_singer_records_into_state -q",
        ),
        notes=(
            "The contract is the Singer output boundary, not a claim that every "
            "tap is production-ready."
        ),
    ),
    DependencyContract(
        name="configured-singer-taps",
        category="connector-boundary",
        active_surface="configured Gmail, Slack, Twenty, Linear, and Google Drive fixture taps",
        status="proved-with-fixtures",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run python scripts/check_connector_contracts.py",
            "uv run pytest tests/runtime/test_connector_contracts.py -q",
        ),
        notes=(
            "Proves the configured tap output contract, state checkpoint handling, raw landing, "
            "SourceRecord adaptation, and adapter failure behavior. Live SaaS auth remains a "
            "separate connector proof before production credentials are wired."
        ),
    ),
    DependencyContract(
        name="slack-live-singer-tap",
        category="connector-boundary",
        active_surface="MeltanoLabs tap-slack auth, discovery, state, raw landing, and adapter",
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run --group pipeline python scripts/check_slack_live_contract.py",
            "uv run pytest tests/etl/extract/test_slack_connectors.py -q",
        ),
        notes=(
            "Uses env/.env-provided SLACK_BOT_TOKEN as TAP_SLACK_API_KEY, runs "
            "tap-slack config validation, discovery, SDK test-record extraction, raw "
            "landing, and Slack-specific SourceRecord adaptation without printing "
            "record content or credentials."
        ),
    ),
    DependencyContract(
        name="twenty-live-custom-singer-tap",
        category="connector-boundary",
        active_surface="fourok tap-fourok-twenty REST extraction, state, raw landing, and adapter",
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run --group pipeline python scripts/check_twenty_live_contract.py",
            "uv run pytest tests/etl/extract/test_twenty_connectors.py -q",
        ),
        notes=(
            "Meltano Hub has no tap-twenty extractor, so the internal-prod path uses a "
            "narrow Singer-compatible extractor for Twenty companies and people. The "
            "live proof runs via Meltano, lands raw JSONL, preserves state, and adapts "
            "records without printing source values or credentials."
        ),
    ),
    DependencyContract(
        name="linear-live-custom-singer-tap",
        category="connector-boundary",
        active_surface=(
            "fourok tap-fourok-linear GraphQL extraction, state, raw landing, and adapter"
        ),
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run --group pipeline python scripts/check_linear_live_contract.py",
            "uv run pytest tests/etl/extract/test_linear_connectors.py -q",
        ),
        notes=(
            "A public Meltano tap-linear exists but requires a separate Python 3.12 runtime. "
            "Internal v0 uses a narrow Singer-compatible extractor for Linear users, issues, "
            "and comments so the connector runs inside the project Python 3.13 app image."
        ),
    ),
    DependencyContract(
        name="google-drive-live-custom-singer-tap",
        category="connector-boundary",
        active_surface=(
            "fourok tap-fourok-google-drive OAuth extraction, state, raw landing, and adapter"
        ),
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run --group pipeline python scripts/check_google_drive_live_contract.py",
            "uv run pytest tests/etl/extract/test_google_drive_tap.py -q",
        ),
        notes=(
            "Uses env/.env-provided Google Workspace OAuth credentials, lists Drive files, "
            "exports Google Docs/text files only, lands raw JSONL, preserves state, and adapts "
            "records without printing document text or credentials."
        ),
    ),
    DependencyContract(
        name="pypdf",
        category="document-extraction",
        active_surface="text-layer PDF to Document SourceRecord adapter",
        status="proved-with-fixtures",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/etl/extract/test_document_extraction.py -q",
            "uv run pytest "
            "tests/test_cli_dashboard_rebuild.py::test_cli_ingests_text_layer_pdf_source_record -q",
        ),
        notes=(
            "OCR, layout extraction, and image PDFs are deliberately outside the active contract."
        ),
    ),
    DependencyContract(
        name="opentelemetry-lgtm",
        category="observability",
        active_surface="safe local traces/logs from CLI and Compose app runtime",
        status="proved",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/runtime/test_telemetry.py -q",
            "docker compose run --rm app observability-smoke "
            "--endpoint http://observability:4318 --service-name fourok-compose-smoke",
        ),
        notes=(
            "Smoke payload exports only operational attributes and asserts no "
            "sensitive payload export."
        ),
    ),
    DependencyContract(
        name="openclaw-plugin-boundary",
        category="agent-integration",
        active_surface=(
            "chat capture adapter, fourok_search_context contract, and local OpenClaw plugin"
        ),
        status="proved-with-adapter-tests",
        dimensions=REQUIRED_DIMENSIONS,
        proof_commands=(
            "uv run pytest tests/retrieval/clients/test_openclaw.py "
            "tests/runtime/test_openclaw_plugin_package.py -q",
        ),
        notes=(
            "This proves the fourok-side adapter and the local plugin package shape. "
            "OpenClaw runtime loading remains a deployment smoke check."
        ),
    ),
)


def dependency_contract_report() -> dict[str, object]:
    contracts = [contract.to_dict() for contract in DEPENDENCY_CONTRACTS]
    missing = [contract["name"] for contract in contracts if contract["missing_dimensions"]]
    accepted_statuses = {
        "proved",
        "proved-with-fake-client",
        "proved-with-fixtures",
        "proved-with-adapter-tests",
        "deferred",
    }
    unproved = [
        contract["name"] for contract in contracts if contract["status"] not in accepted_statuses
    ]
    return {
        "required_dimensions": list(REQUIRED_DIMENSIONS),
        "contracts": contracts,
        "summary": {
            "total": len(contracts),
            "missing_dimension_count": len(missing),
            "unproved_count": len(unproved),
        },
        "status": "ok" if not missing and not unproved else "failed",
    }
