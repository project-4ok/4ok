from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from gcb.secrets.infisical import InfisicalConfig, SecretProviderError, fetch_infisical_secrets

DEFAULT_STATE = Path(".gcb-state.sqlite")

HonchoHttpClient = None
build_honcho_sync_plan = None
load_honcho_fixture = None
source_connection_preflight = None
source_secret_preflight = None
SourceClientError = None
collect_source_snapshot = None
HonchoSyncState = None
execute_honcho_sync = None
graphiti_episodes_from_source_snapshot = None
evaluate_evidence_baseline = None


def _ensure_honcho_experiment_symbols() -> None:
    global build_honcho_sync_plan, load_honcho_fixture
    if build_honcho_sync_plan is None or load_honcho_fixture is None:
        module = importlib.import_module("gcb.honcho.experiment")

        if build_honcho_sync_plan is None:
            build_honcho_sync_plan = module.build_honcho_sync_plan
        if load_honcho_fixture is None:
            load_honcho_fixture = module.load_honcho_fixture


def _ensure_honcho_client_symbol() -> None:
    global HonchoHttpClient
    if HonchoHttpClient is None:
        module = importlib.import_module("gcb.honcho.client")
        HonchoHttpClient = module.HonchoHttpClient


def _ensure_honcho_preflight_symbols() -> None:
    global source_connection_preflight, source_secret_preflight
    if source_connection_preflight is None or source_secret_preflight is None:
        module = importlib.import_module("gcb.honcho.preflight")

        if source_connection_preflight is None:
            source_connection_preflight = module.source_connection_preflight
        if source_secret_preflight is None:
            source_secret_preflight = module.source_secret_preflight


def _ensure_honcho_source_symbols() -> None:
    global SourceClientError, collect_source_snapshot
    if SourceClientError is None or collect_source_snapshot is None:
        module = importlib.import_module("gcb.honcho.sources")

        if SourceClientError is None:
            SourceClientError = module.SourceClientError
        if collect_source_snapshot is None:
            collect_source_snapshot = module.collect_source_snapshot


def _ensure_honcho_state_symbol() -> None:
    global HonchoSyncState
    if HonchoSyncState is None:
        module = importlib.import_module("gcb.honcho.state")
        HonchoSyncState = module.HonchoSyncState


def _ensure_honcho_sync_symbol() -> None:
    global execute_honcho_sync
    if execute_honcho_sync is None:
        module = importlib.import_module("gcb.honcho.sync")
        execute_honcho_sync = module.execute_honcho_sync


def _ensure_graphiti_episode_symbol() -> None:
    global graphiti_episodes_from_source_snapshot
    if graphiti_episodes_from_source_snapshot is None:
        module = importlib.import_module("gcb.retrieval.graphiti_episodes")
        graphiti_episodes_from_source_snapshot = module.graphiti_episodes_from_source_snapshot


def _ensure_evidence_baseline_symbol() -> None:
    global evaluate_evidence_baseline
    if evaluate_evidence_baseline is None:
        module = importlib.import_module("gcb.retrieval.evidence_baseline")
        evaluate_evidence_baseline = module.evaluate_evidence_baseline


def _honcho_sync_data_from_args(args: argparse.Namespace) -> dict[str, object]:
    if args.fixture is not None:
        _ensure_honcho_experiment_symbols()
        try:
            return load_honcho_fixture(args.fixture)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    _ensure_honcho_source_symbols()
    if not args.infisical_project_id:
        raise SystemExit("--live-sources requires --infisical-project-id")
    if args.source_limit < 1:
        raise SystemExit("--source-limit must be a positive integer")
    if args.catalog_limit < 1:
        raise SystemExit("--catalog-limit must be a positive integer")
    if args.checkpoint_overlap_minutes < 0:
        raise SystemExit("--checkpoint-overlap-minutes must be a non-negative integer")

    try:
        secrets = fetch_infisical_secrets(
            InfisicalConfig(
                project_id=args.infisical_project_id,
                environment=args.infisical_env,
                path=args.infisical_path,
                domain=args.infisical_domain,
            ),
            allow_cli_fallback=True,
        )
    except (RuntimeError, SecretProviderError, SourceClientError) as exc:
        raise SystemExit(str(exc)) from exc
    try:
        return collect_source_snapshot(
            secrets,
            limit=args.source_limit,
            catalog_limit=args.catalog_limit,
            sources=_parse_honcho_sources(args.sources),
            checkpoints=_honcho_live_checkpoints_from_args(args),
            overlap_minutes=args.checkpoint_overlap_minutes,
        )
    except SourceClientError as exc:
        raise SystemExit(str(exc)) from exc


def _parse_honcho_sources(value: str) -> set[str]:
    _ensure_honcho_source_symbols()
    sources = {item.strip().lower() for item in value.split(",") if item.strip()}
    if not sources:
        raise SourceClientError("--sources must include at least one source")
    return sources


def _honcho_live_checkpoints_from_args(args: argparse.Namespace) -> dict[str, str]:
    state_path = _honcho_sync_state_path(args) if args.write or args.state is not None else None
    if state_path is None:
        return {}
    _ensure_honcho_state_symbol()
    try:
        return HonchoSyncState.load(state_path).checkpoints
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _honcho_planning_state_from_args(args: argparse.Namespace) -> HonchoSyncState | None:
    if not args.write and args.state is None:
        return None
    _ensure_honcho_state_symbol()
    try:
        return HonchoSyncState.load(_honcho_sync_state_path(args))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _honcho_sync_state_path(args: argparse.Namespace) -> Path:
    return args.state or Path(".local/honcho-sync-state.json")


def _honcho_readback_has_source_ref(readback: object, source_ref: object) -> bool:
    if not isinstance(source_ref, str) or not source_ref:
        return False
    items = readback.get("items") if isinstance(readback, dict) else readback
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if isinstance(metadata, dict) and metadata.get("source_ref") == source_ref:
            return True
    return False


def _load_honcho_eval_cases(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read Honcho eval cases: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Honcho eval cases JSON: {path}") from exc
    if not isinstance(data, list):
        raise ValueError("Honcho eval cases must be a JSON list")
    cases = [item for item in data if isinstance(item, dict)]
    if len(cases) != len(data):
        raise ValueError("Honcho eval cases must contain only objects")
    for index, case in enumerate(cases, start=1):
        if not isinstance(case.get("query"), str) or not case.get("query"):
            raise ValueError(f"Honcho eval case {index} requires query")
        expected = case.get("expected_source_refs", [])
        if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
            raise ValueError(f"Honcho eval case {index} expected_source_refs must be strings")
        expected_entities = case.get("expected_entities", [])
        if not isinstance(expected_entities, list) or not all(
            isinstance(item, str) for item in expected_entities
        ):
            raise ValueError(f"Honcho eval case {index} expected_entities must be strings")
        expected_permission_refs = case.get("expected_permission_refs", [])
        if not isinstance(expected_permission_refs, list) or not all(
            isinstance(item, str) for item in expected_permission_refs
        ):
            raise ValueError(f"Honcho eval case {index} expected_permission_refs must be strings")
    return cases


def _evaluate_honcho_retrieval(
    *,
    client: HonchoHttpClient,
    cases: list[dict[str, object]],
    limit: int,
) -> dict[str, object]:
    if limit < 1:
        raise ValueError("--limit must be a positive integer")
    case_reports = [_evaluate_honcho_case(client=client, case=case, limit=limit) for case in cases]
    passed = sum(1 for item in case_reports if item["passed"])
    top1_hits = sum(1 for item in case_reports if item["top1_hit"])
    top3_hits = sum(1 for item in case_reports if item["top3_hit"])
    provenance_cases = sum(1 for item in case_reports if item["top_source_refs"])
    failed = len(case_reports) - passed
    return {
        "status": "ok" if failed == 0 else "needs_review",
        "summary": {
            "cases": len(case_reports),
            "passed": passed,
            "failed": failed,
            "top1_hits": top1_hits,
            "top3_hits": top3_hits,
            "provenance_cases": provenance_cases,
        },
        "cases": case_reports,
    }


def _evaluate_honcho_case(
    *,
    client: HonchoHttpClient,
    case: dict[str, object],
    limit: int,
) -> dict[str, object]:
    query = str(case["query"])
    expected = [item for item in case.get("expected_source_refs", []) if isinstance(item, str)]
    expected_entities = [
        item for item in case.get("expected_entities", []) if isinstance(item, str)
    ]
    expected_permission_refs = [
        item for item in case.get("expected_permission_refs", []) if isinstance(item, str)
    ]
    results = _honcho_eval_search(client=client, case=case, query=query, limit=limit)
    messages = _honcho_eval_messages(results)
    source_refs = [_honcho_message_source_ref(message) for message in messages]
    top_source_refs = [source_ref for source_ref in source_refs if source_ref]
    top_entities = _honcho_top_metadata_refs(
        messages,
        keys=("candidate_entities", "actors", "assignees", "employee_peer"),
    )
    top_permission_refs = _honcho_top_metadata_refs(messages, keys=("permission_refs",))
    found_expected = [source_ref for source_ref in expected if source_ref in top_source_refs]
    found_entities = [entity for entity in expected_entities if entity in top_entities]
    found_permission_refs = [ref for ref in expected_permission_refs if ref in top_permission_refs]
    top1_hit = bool(expected and top_source_refs[:1] and top_source_refs[0] in expected)
    top3_hit = bool(expected and set(expected).intersection(top_source_refs[:3]))
    source_refs_passed = bool(found_expected) if expected else bool(top_source_refs)
    entities_passed = bool(found_entities) if expected_entities else True
    permissions_passed = bool(found_permission_refs) if expected_permission_refs else True
    passed = source_refs_passed and entities_passed and permissions_passed
    return {
        "id": case.get("id") or query,
        "category": case.get("category") if isinstance(case.get("category"), str) else None,
        "query": query,
        "scope": _honcho_eval_scope(case),
        "expected_source_refs": expected,
        "found_expected_source_refs": found_expected,
        "expected_entities": expected_entities,
        "found_expected_entities": found_entities,
        "expected_permission_refs": expected_permission_refs,
        "found_expected_permission_refs": found_permission_refs,
        "top_source_refs": top_source_refs,
        "top_entities": top_entities,
        "top_permission_refs": top_permission_refs,
        "top1_hit": top1_hit,
        "top3_hit": top3_hit,
        "passed": passed,
        "failure_reason": _failure_reason(
            source_refs_passed=source_refs_passed,
            entities_passed=entities_passed,
            permissions_passed=permissions_passed,
        ),
        "result_count": len(messages),
        "top_peer_id": _honcho_message_field(messages[:1], "peer_id"),
        "top_session_id": _honcho_message_field(messages[:1], "session_id"),
        "top_content_preview": _honcho_content_preview(messages[:1]),
    }


def _honcho_eval_search(
    *,
    client: HonchoHttpClient,
    case: dict[str, object],
    query: str,
    limit: int,
) -> object:
    filters = case.get("filters") if isinstance(case.get("filters"), dict) else None
    peer_id = case.get("peer_id")
    session_id = case.get("session_id")
    if isinstance(peer_id, str) and peer_id:
        return client.search_peer(peer_id=peer_id, query=query, filters=filters, limit=limit)
    if isinstance(session_id, str) and session_id:
        return client.search_session(
            session_id=session_id,
            query=query,
            filters=filters,
            limit=limit,
        )
    return client.search_messages(query=query, filters=filters, limit=limit)


def _honcho_eval_messages(results: object) -> list[object]:
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        items = results.get("items")
        if isinstance(items, list):
            return items
    return []


def _honcho_eval_scope(case: dict[str, object]) -> dict[str, str]:
    if isinstance(case.get("peer_id"), str) and case["peer_id"]:
        return {"type": "peer", "id": str(case["peer_id"])}
    if isinstance(case.get("session_id"), str) and case["session_id"]:
        return {"type": "session", "id": str(case["session_id"])}
    return {"type": "workspace", "id": ""}


def _honcho_message_source_ref(message: object) -> str | None:
    if not isinstance(message, dict):
        return None
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("source_ref"), str):
        return metadata["source_ref"]
    return None


def _honcho_top_metadata_refs(messages: list[object], *, keys: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in keys:
            _extend_unique_strings(refs, metadata.get(key))
    return refs


def _extend_unique_strings(values: list[str], value: object) -> None:
    if isinstance(value, str) and value and value not in values:
        values.append(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item and item not in values:
                values.append(item)


def _failure_reason(
    *,
    source_refs_passed: bool,
    entities_passed: bool,
    permissions_passed: bool,
) -> str | None:
    reasons: list[str] = []
    if not source_refs_passed:
        reasons.append("missing_expected_source_refs")
    if not entities_passed:
        reasons.append("missing_expected_entities")
    if not permissions_passed:
        reasons.append("missing_expected_permission_refs")
    return ",".join(reasons) if reasons else None


def _honcho_message_field(messages: list[object], field: str) -> str | None:
    if not messages or not isinstance(messages[0], dict):
        return None
    value = messages[0].get(field)
    return value if isinstance(value, str) else None


def _honcho_content_preview(messages: list[object], *, limit: int = 160) -> str | None:
    value = _honcho_message_field(messages, "content")
    if value is None:
        return None
    return value if len(value) <= limit else f"{value[:limit].rstrip()}..."


def _honcho_smoke_search_probe(
    client: HonchoHttpClient,
    smoke_message,
    source_ref: object,
) -> dict[str, object]:
    try:
        search_results = client.search_messages(query=smoke_message.text, filters=None, limit=5)
    except OSError as exc:
        return {
            "source_ref": source_ref,
            "status": "error",
            "reason": str(exc),
        }
    return {
        "source_ref": source_ref,
        "found": _honcho_readback_has_source_ref(search_results, source_ref),
    }
