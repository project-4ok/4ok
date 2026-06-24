from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fourok.honcho.experiment import load_honcho_fixture
from fourok.retrieval.evidence_baseline import search_evidence
from fourok.retrieval.graphiti_episodes import graphiti_episodes_from_source_snapshot

DEFAULT_FIXTURE = Path("fixtures/context_substrate/source_snapshot_eval.json")
DEFAULT_CASES = Path("fixtures/context_substrate/context_substrate_cases.json")


def main() -> None:
    args = _parser().parse_args()
    try:
        report = asyncio.run(_run(args))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2))


async def _run(args: argparse.Namespace) -> dict[str, object]:
    Graphiti, EpisodeType = _load_graphiti()
    data = load_honcho_fixture(args.fixture)
    cases = _load_cases(args.cases)
    graphiti = Graphiti(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    try:
        await graphiti.build_indices_and_constraints()
        if args.clear:
            await _clear_group(graphiti, args.group_id)
        episodes = graphiti_episodes_from_source_snapshot(data, group_id=args.group_id)
        episode_lookup: dict[str, str] = {}
        for episode in episodes:
            result = await graphiti.add_episode(
                group_id=str(episode["group_id"]),
                name=str(episode["name"]),
                episode_body=str(episode["episode_body"]),
                source_description=str(episode["source_description"]),
                reference_time=_reference_time(episode.get("reference_time")),
                source=EpisodeType.from_str(str(episode["source"])),
            )
            if episode_uuid := _added_episode_uuid(result):
                episode_lookup[episode_uuid] = _episode_provenance_text(episode)
        report = await evaluate_graphiti_cases(
            graphiti,
            cases=cases,
            group_id=args.group_id,
            limit=args.limit,
            episode_lookup=episode_lookup,
            source_data=data,
        )
        return {
            "substrate": "graphiti",
            "group_id": args.group_id,
            "ingested_episodes": len(episodes),
            **report,
        }
    finally:
        close = getattr(graphiti, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


async def evaluate_graphiti_cases(
    graphiti: Any,
    *,
    cases: list[dict[str, object]],
    group_id: str,
    limit: int,
    episode_lookup: dict[str, str] | None = None,
    source_data: dict[str, object] | None = None,
) -> dict[str, object]:
    if limit < 1:
        raise ValueError("--limit must be a positive integer")
    case_reports = [
        await _evaluate_graphiti_case(
            graphiti,
            case=case,
            group_id=group_id,
            limit=limit,
            episode_lookup=episode_lookup,
            source_data=source_data,
        )
        for case in cases
    ]
    passed = sum(1 for item in case_reports if item["passed"])
    failed = len(case_reports) - passed
    return {
        "status": "ok" if failed == 0 else "needs_review",
        "summary": {
            "cases": len(case_reports),
            "passed": passed,
            "failed": failed,
            "top1_hits": sum(1 for item in case_reports if item["top1_hit"]),
            "top3_hits": sum(1 for item in case_reports if item["top3_hit"]),
            "provenance_cases": sum(1 for item in case_reports if item["top_source_refs"]),
            "graphiti_only_passed": sum(1 for item in case_reports if item["graphiti_only_passed"]),
            "source_fallback_cases": sum(
                1 for item in case_reports if item["source_fallback_used"]
            ),
            "source_fallback_items": sum(
                int(item["source_fallback_count"]) for item in case_reports
            ),
        },
        "cases": case_reports,
    }


async def _evaluate_graphiti_case(
    graphiti: Any,
    *,
    case: dict[str, object],
    group_id: str,
    limit: int,
    episode_lookup: dict[str, str] | None = None,
    source_data: dict[str, object] | None = None,
) -> dict[str, object]:
    query = str(case["query"])
    expected_source_refs = [
        item for item in case.get("expected_source_refs", []) if isinstance(item, str)
    ]
    expected_entities = [
        item for item in case.get("expected_entities", []) if isinstance(item, str)
    ]
    expected_permission_refs = [
        item for item in case.get("expected_permission_refs", []) if isinstance(item, str)
    ]
    graphiti_facts = await _graphiti_search_texts(
        graphiti,
        query=query,
        group_id=group_id,
        limit=limit,
        episode_lookup=episode_lookup,
    )
    graphiti_top_source_refs = _ordered_matches(graphiti_facts, expected_source_refs)
    graphiti_top_entities = _ordered_matches(graphiti_facts, expected_entities)
    graphiti_top_permission_refs = _ordered_matches(graphiti_facts, expected_permission_refs)
    graphiti_source_refs_passed = (
        bool(graphiti_top_source_refs) if expected_source_refs else bool(graphiti_facts)
    )
    graphiti_entities_passed = bool(graphiti_top_entities) if expected_entities else True
    graphiti_permissions_passed = (
        bool(graphiti_top_permission_refs) if expected_permission_refs else True
    )
    fallback_facts = _source_fallback_texts(source_data, query=query, limit=limit)
    result_facts = [*graphiti_facts, *fallback_facts]
    top_source_refs = _ordered_matches(result_facts, expected_source_refs)
    top_entities = _ordered_matches(result_facts, expected_entities)
    top_permission_refs = _ordered_matches(result_facts, expected_permission_refs)
    found_source_refs = [
        source_ref for source_ref in expected_source_refs if source_ref in top_source_refs
    ]
    found_entities = [entity for entity in expected_entities if entity in top_entities]
    found_permission_refs = [ref for ref in expected_permission_refs if ref in top_permission_refs]
    source_refs_passed = bool(found_source_refs) if expected_source_refs else bool(result_facts)
    entities_passed = bool(found_entities) if expected_entities else True
    permissions_passed = bool(found_permission_refs) if expected_permission_refs else True
    return {
        "id": case.get("id") or query,
        "category": case.get("category") if isinstance(case.get("category"), str) else None,
        "query": query,
        "expected_source_refs": expected_source_refs,
        "found_expected_source_refs": found_source_refs,
        "expected_entities": expected_entities,
        "found_expected_entities": found_entities,
        "expected_permission_refs": expected_permission_refs,
        "found_expected_permission_refs": found_permission_refs,
        "graphiti_only_found_expected_source_refs": graphiti_top_source_refs,
        "graphiti_only_found_expected_entities": graphiti_top_entities,
        "graphiti_only_found_expected_permission_refs": graphiti_top_permission_refs,
        "graphiti_only_passed": (
            graphiti_source_refs_passed and graphiti_entities_passed and graphiti_permissions_passed
        ),
        "top_source_refs": top_source_refs,
        "top_entities": top_entities,
        "top_permission_refs": top_permission_refs,
        "top1_hit": bool(
            expected_source_refs
            and top_source_refs[:1]
            and top_source_refs[0] in expected_source_refs
        ),
        "top3_hit": bool(
            expected_source_refs and set(expected_source_refs).intersection(top_source_refs[:3])
        ),
        "passed": source_refs_passed and entities_passed and permissions_passed,
        "failure_reason": _failure_reason(
            source_refs_passed=source_refs_passed,
            entities_passed=entities_passed,
            permissions_passed=permissions_passed,
        ),
        "result_count": len(result_facts),
        "graphiti_result_count": len(graphiti_facts),
        "source_fallback_count": len(fallback_facts),
        "source_fallback_used": bool(fallback_facts),
        "top_facts": result_facts[:limit],
    }


def _load_graphiti():
    try:
        from graphiti_core import Graphiti
        from graphiti_core.nodes import EpisodeType
    except ImportError as exc:
        raise RuntimeError(
            "graphiti-core is required; run through docker/graphiti-runner.Dockerfile"
        ) from exc
    return Graphiti, EpisodeType


async def _graphiti_search_texts(
    graphiti: Any,
    *,
    query: str,
    group_id: str,
    limit: int,
    episode_lookup: dict[str, str] | None = None,
) -> list[str]:
    search_structured = getattr(graphiti, "search_", None)
    if search_structured is not None:
        results = await search_structured(
            query=query,
            group_ids=[group_id],
            config=_structured_search_config(limit),
        )
        texts = _structured_result_texts(results, limit=limit)
        if episode_lookup is not None:
            texts = _structured_result_texts(
                results,
                limit=limit,
                episode_lookup=episode_lookup,
            )
        if texts:
            return texts

    results = await graphiti.search(group_ids=[group_id], query=query, num_results=limit)
    return [_result_fact(result) for result in results]


def _structured_search_config(limit: int) -> object:
    try:
        from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
    except ImportError:
        return None
    config = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
    config.limit = limit
    return config


def _structured_result_texts(
    results: object,
    *,
    limit: int,
    episode_lookup: dict[str, str] | None = None,
) -> list[str]:
    texts: list[str] = []
    for edge in getattr(results, "edges", []):
        edge_parts: list[str] = []
        _append_text(edge_parts, getattr(edge, "fact", None))
        if episode_lookup:
            for episode_uuid in _edge_episode_uuids(edge):
                _append_text(edge_parts, episode_lookup.get(episode_uuid))
        _append_text(texts, "\n".join(edge_parts))
    for episode in getattr(results, "episodes", []):
        _append_text(texts, getattr(episode, "name", None))
        _append_text(texts, getattr(episode, "content", None))
    return texts[:limit]


def _added_episode_uuid(result: object) -> str | None:
    episode = getattr(result, "episode", None)
    value = getattr(episode, "uuid", None)
    return value if isinstance(value, str) and value else None


def _episode_provenance_text(episode: dict[str, object]) -> str:
    metadata = episode.get("metadata")
    source_url = ""
    source_updated_at = ""
    entities: list[str] = []
    permission_refs: list[str] = []
    if isinstance(metadata, dict):
        source_url = _string_value(metadata.get("source_url"))
        source_updated_at = _string_value(metadata.get("source_updated_at"))
        entities = _string_list(metadata.get("entities"))
        permission_refs = _string_list(metadata.get("permission_refs"))
    return (
        f"source_ref: {episode.get('name') or ''}\n"
        f"source_url: {source_url}\n"
        f"source_updated_at: {source_updated_at}\n"
        f"entities: {' '.join(entities)}\n"
        f"permission_refs: {' '.join(permission_refs)}"
    )


def _edge_episode_uuids(edge: object) -> list[str]:
    value = getattr(edge, "episodes", None)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _source_fallback_texts(
    source_data: dict[str, object] | None,
    *,
    query: str,
    limit: int,
) -> list[str]:
    if source_data is None:
        return []
    pack = search_evidence(source_data, query, limit=limit)
    evidence = pack.get("evidence")
    if not isinstance(evidence, list):
        return []
    return [
        _evidence_text(item) for item in evidence if isinstance(item, dict) and _evidence_text(item)
    ]


def _evidence_text(item: dict[str, object]) -> str:
    entities = _string_list(item.get("entities"))
    permission_refs = _string_list(item.get("permission_refs"))
    return (
        f"source_ref: {_string_value(item.get('source_ref'))}\n"
        f"source_url: {_string_value(item.get('source_url'))}\n"
        f"source_updated_at: {_string_value(item.get('source_updated_at'))}\n"
        f"entities: {' '.join(entities)}\n"
        f"permission_refs: {' '.join(permission_refs)}\n"
        f"snippet: {_string_value(item.get('snippet'))}"
    )


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


async def _clear_group(graphiti: Any, group_id: str) -> None:
    delete_group = getattr(graphiti, "delete_group", None)
    if delete_group is not None:
        await delete_group(group_id)


def _load_cases(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read Graphiti eval cases: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Graphiti eval cases JSON: {path}") from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("Graphiti eval cases must be a JSON list of objects")
    return data


def _reference_time(value: object) -> datetime:
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(UTC)


def _result_fact(result: object) -> str:
    for field in ("fact", "content", "name"):
        value = getattr(result, field, None)
        if isinstance(value, str):
            return value
    return str(result)


def _append_text(texts: list[str], value: object) -> None:
    if isinstance(value, str) and value and value not in texts:
        texts.append(value)


def _ordered_matches(facts: list[str], expected_values: list[str]) -> list[str]:
    matches: list[str] = []
    for fact in facts:
        for expected in expected_values:
            if expected in fact and expected not in matches:
                matches.append(expected)
    return matches


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Graphiti context-substrate eval.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--group-id", default=os.environ.get("GRAPHITI_GROUP_ID", "fourok-eval"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    return parser


if __name__ == "__main__":
    main()
