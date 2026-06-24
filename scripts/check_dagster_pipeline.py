from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

from dagster import materialize
from sqlalchemy import create_engine, text

from fourok.governance.context import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.runtime.webhooks import WebhookEventInput, enqueue_webhook_event, webhook_event_rows

EXPECTED_ASSETS = {
    "fourok_audit_metadata",
    "fourok_canonical_objects_and_entity_links",
    "fourok_google_drive_live_source_records_from_raw_landing",
    "fourok_linear_live_source_records_from_raw_landing",
    "fourok_operator_dashboard",
    "fourok_retrieval_records",
    "fourok_slack_live_source_records_from_raw_landing",
    "fourok_twenty_live_source_records_from_raw_landing",
    "fourok_webhook_backlog",
    "meltano_google_drive_live_raw_landing",
    "meltano_linear_live_raw_landing",
    "meltano_slack_live_raw_landing",
    "meltano_twenty_live_raw_landing",
}

FIXTURE_ASSETS: set[str] = set()

LIVE_CONNECTOR_ASSETS = {
    name for name in EXPECTED_ASSETS if "_live_" in name or name.endswith("_live_raw_landing")
}


def main() -> None:
    _load_dotenv_defaults(Path(".env"))
    parser = argparse.ArgumentParser(description="Check the repository Dagster asset graph.")
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Run deterministic fixture assets into a project-local regression sandbox.",
    )
    parser.add_argument(
        "--materialize-live-connectors",
        action="store_true",
        help="Run the live connector asset path through Dagster with env/.env credentials.",
    )
    parser.add_argument(
        "--verify-live-db",
        action="store_true",
        help="Require FOUR_OK_DATABASE_URL and verify live Dagster import changes runtime DB rows.",
    )
    parser.add_argument(
        "--live-connector",
        choices=("all", "slack", "twenty", "linear", "google_drive"),
        default="all",
        help="Limit --materialize-live-connectors to one live connector.",
    )
    parser.add_argument(
        "--verify-retrieval",
        action="store_true",
        help="Verify search, evidence, and audit against the materialized 4OK state.",
    )
    parser.add_argument(
        "--verify-webhook",
        action="store_true",
        help="Seed and verify a pending webhook event processed by Dagster.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".local/test-artifacts/dagster-pipeline-proof"),
        help="Ignored directory used for materialization state.",
    )
    args = parser.parse_args()

    module = _load_definitions()
    asset_names = {
        key.to_user_string() for key in module.defs.resolve_asset_graph().get_all_asset_keys()
    }
    if asset_names != EXPECTED_ASSETS:
        missing = sorted(EXPECTED_ASSETS - asset_names)
        unexpected = sorted(asset_names - EXPECTED_ASSETS)
        raise SystemExit(f"Dagster asset graph mismatch. missing={missing} unexpected={unexpected}")

    print(f"asset_count={len(asset_names)}")
    for asset_name in sorted(asset_names):
        print(asset_name)

    if args.materialize:
        _materialize_assets(
            module,
            args.artifact_dir,
            seed_webhook=args.verify_webhook,
            asset_names=FIXTURE_ASSETS,
            load_dotenv=False,
        )
        print("materialize_status=ok")
    if args.materialize_live_connectors:
        before_counts = _runtime_db_counts() if args.verify_live_db else {}
        _materialize_assets(
            module,
            args.artifact_dir,
            seed_webhook=False,
            asset_names=_live_connector_asset_names(args.live_connector),
            load_dotenv=True,
            database_url=os.environ.get("FOUR_OK_DATABASE_URL", "") if args.verify_live_db else "",
        )
        print("live_connector_materialize_status=ok")
        if args.verify_live_db:
            _verify_live_db_changed(before_counts)
    if args.verify_retrieval:
        _verify_retrieval(args.artifact_dir / "fourok-state.sqlite")
    if args.verify_webhook:
        _verify_webhook(args.artifact_dir / "fourok-state.sqlite")


def _load_definitions() -> Any:
    definitions_path = Path("deploy/dagster/definitions.py")
    spec = importlib.util.spec_from_file_location(
        "fourok_dagster_definitions_check", definitions_path
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load {definitions_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialize_assets(
    module: Any,
    artifact_dir: Path,
    *,
    seed_webhook: bool,
    asset_names: set[str],
    load_dotenv: bool,
    database_url: str = "",
) -> None:
    shutil.rmtree(artifact_dir, ignore_errors=True)
    raw_landing = artifact_dir / "raw"
    state_path = artifact_dir / "fourok-state.sqlite"
    if seed_webhook:
        _seed_webhook_event(state_path)
    selected_assets = [
        asset_def
        for asset_def in module.defs.assets
        if {key.to_user_string() for key in asset_def.keys}.issubset(asset_names)
    ]
    result = materialize(
        selected_assets,
        resources={
            "raw_landing": module.RawLandingResource(path=str(raw_landing)),
            "meltano_project": module.MeltanoProjectResource(project_root="."),
            "connector_env": module.ConnectorEnvResource(
                dotenv_path=os.environ.get("FOUR_OK_DOTENV_PATH", ".env"),
                load_dotenv=load_dotenv,
            ),
            "fourok_runtime": module.FourokRuntimeResource(
                state_path=str(state_path),
                database_url=database_url,
            ),
        },
    )
    if not result.success:
        raise SystemExit("Dagster materialization failed")


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return default


def _load_dotenv_defaults(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _live_connector_asset_names(connector: str) -> set[str]:
    if connector == "all":
        return LIVE_CONNECTOR_ASSETS
    asset_prefix = f"meltano_{connector}_live_raw_landing"
    import_prefix = f"fourok_{connector}_live_source_records_from_raw_landing"
    return {asset_prefix, import_prefix}


def _runtime_db_counts() -> dict[str, int]:
    database_url = os.environ.get("FOUR_OK_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("--verify-live-db requires FOUR_OK_DATABASE_URL")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return {
                "source_records": int(
                    connection.execute(text("SELECT count(*) FROM source_records")).scalar_one()
                ),
                "retrieval_records": int(
                    connection.execute(text("SELECT count(*) FROM retrieval_records")).scalar_one()
                ),
            }
    finally:
        engine.dispose()


def _verify_live_db_changed(before_counts: dict[str, int]) -> None:
    after_counts = _runtime_db_counts()
    source_delta = after_counts["source_records"] - before_counts["source_records"]
    retrieval_delta = after_counts["retrieval_records"] - before_counts["retrieval_records"]
    if after_counts["source_records"] <= 0 or after_counts["retrieval_records"] <= 0:
        raise SystemExit(
            "Live Dagster import left runtime DB empty: "
            f"source_records_after={after_counts['source_records']} "
            f"retrieval_records_after={after_counts['retrieval_records']}"
        )
    if source_delta < 0 or retrieval_delta < 0:
        raise SystemExit(
            "Live Dagster import decreased runtime DB rows: "
            f"source_records_delta={source_delta} retrieval_records_delta={retrieval_delta}"
        )
    print(f"live_db_source_records_before={before_counts['source_records']}")
    print(f"live_db_source_records_after={after_counts['source_records']}")
    print(f"live_db_source_records_delta={source_delta}")
    print(f"live_db_retrieval_records_before={before_counts['retrieval_records']}")
    print(f"live_db_retrieval_records_after={after_counts['retrieval_records']}")
    print(f"live_db_retrieval_records_delta={retrieval_delta}")
    print("live_db_current_status=ok")


def _seed_webhook_event(state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="dagster-proof-webhook-1",
            source_system="linear",
            source_object_id="OPS-DAGSTER",
            event_type="issue.updated",
            operation="upsert",
            idempotency_key="linear:OPS-DAGSTER:updated:1",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:OPS-DAGSTER",
                    "source_system": "linear",
                    "source_id": "OPS-DAGSTER",
                    "record_type": "work_item",
                    "title": "Dagster webhook proof",
                    "body": "Dagster webhook backlog proof marker.",
                    "author_ref": "linear:user:olivia",
                }
            },
        ),
    )


def _verify_retrieval(state_path: Path) -> None:
    if not state_path.exists():
        raise SystemExit(f"Missing {state_path}; run with --materialize before --verify-retrieval")

    context = GovernedContext(state_path)
    retrieval_units = context.retrieval_units()
    if not retrieval_units:
        raise SystemExit("No retrieval units found after Dagster materialization")

    audit_count_before = len(context.audit_events())
    response = context.search_context("Alpha cancellation refund evidence", limit=5)
    if not response.results:
        raise SystemExit("Post-Dagster retrieval search returned no results")
    if not response.evidence_items:
        raise SystemExit("Post-Dagster retrieval search returned no evidence items")
    if not response.audit_ref:
        raise SystemExit("Post-Dagster retrieval search did not return an audit ref")

    new_events = context.audit_events()[audit_count_before:]
    event_types = {str(event.get("event_type")) for event in new_events}
    if not {"search", "source_access"}.issubset(event_types):
        raise SystemExit(f"Missing expected audit events: {sorted(event_types)}")

    print(f"retrieval_unit_count={len(retrieval_units)}")
    print(f"search_result_count={len(response.results)}")
    print(f"evidence_item_count={len(response.evidence_items)}")
    print(f"audit_event_types={','.join(sorted(event_types))}")


def _verify_webhook(state_path: Path) -> None:
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    rows = webhook_event_rows(state)
    proof_rows = [row for row in rows if row["event_id"] == "dagster-proof-webhook-1"]
    if not proof_rows or proof_rows[0]["status"] != "succeeded":
        raise SystemExit(f"Dagster webhook proof did not succeed: {proof_rows}")

    context = GovernedContext(state_path)
    response = context.search_context("Dagster webhook backlog proof marker", limit=3)
    source_refs = [result.source_ref for result in response.results]
    if "linear:issue:OPS-DAGSTER" not in source_refs:
        raise SystemExit(f"Webhook source record is not searchable: {source_refs}")

    print("webhook_status=succeeded")
    print("webhook_search_ref=linear:issue:OPS-DAGSTER")


if __name__ == "__main__":
    main()
