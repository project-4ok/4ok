from __future__ import annotations

import json
import re

from opentelemetry import trace

from gcb.observability import record_histogram
from gcb.retrieval.search import SearchResult


def build_evidence_pack(
    *,
    query: str = "",
    results: list[SearchResult],
    source_records: list[dict[str, object]],
    canonical_objects: list[dict[str, object]],
    entity_links: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("gcb.evidence_pack.build") as span:
        pack = _build_evidence_pack(
            query=query,
            results=results,
            source_records=source_records,
            canonical_objects=canonical_objects,
            entity_links=entity_links,
        )
        span.set_attribute("gcb.evidence_pack.result_count", len(results))
        span.set_attribute("gcb.evidence_pack.source_record_count", len(source_records))
        span.set_attribute("gcb.evidence_pack.canonical_object_count", len(canonical_objects))
        span.set_attribute("gcb.evidence_pack.entity_link_count", len(entity_links or []))
        span.set_attribute(
            "gcb.evidence_pack.evidence_item_count",
            len(pack.get("evidence_items", [])),
        )
        span.set_attribute(
            "gcb.evidence_pack.related_object_count",
            len(pack.get("related_objects", [])),
        )
        span.set_attribute(
            "gcb.evidence_pack.unresolved_candidate_count",
            len(pack.get("unresolved_candidates", [])),
        )
        span.set_attribute(
            "gcb.evidence_pack.limitation_count",
            len(pack.get("limitations", [])),
        )
        record_histogram("gcb_evidence_pack_items", len(pack.get("evidence_items", [])))
        record_histogram("gcb_evidence_pack_limitations", len(pack.get("limitations", [])))
        return pack


def _build_evidence_pack(
    *,
    query: str = "",
    results: list[SearchResult],
    source_records: list[dict[str, object]],
    canonical_objects: list[dict[str, object]],
    entity_links: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    source_by_ref = {str(row["source_ref"]): row for row in source_records}
    entity_links = entity_links or []
    evidence_refs = {result.source_ref for result in results}
    visible_source_refs = {str(row["source_ref"]) for row in source_records}
    object_by_source_ref = _object_by_source_ref(
        canonical_objects,
        visible_source_refs=visible_source_refs,
    )
    visible_object_refs = {
        str(context_object["object_ref"]) for context_object in object_by_source_ref.values()
    }
    visible_entity_links = [
        link
        for link in entity_links
        if str(link["source_ref"]) in visible_source_refs
        and str(link["object_ref"]) in visible_object_refs
    ]
    links_by_source_ref = _links_by_source_ref(visible_entity_links)
    related_objects = _related_objects(
        results=results,
        source_records=source_records,
        object_by_source_ref=object_by_source_ref,
        entity_links=visible_entity_links,
        evidence_refs=evidence_refs,
    )
    return {
        "query": query,
        "summary": _summary(results),
        "result_candidates": [
            _result_candidate(result, source_by_ref.get(result.source_ref)) for result in results
        ],
        "evidence_items": [
            _evidence_item(
                result,
                source_by_ref.get(result.source_ref),
                object_by_source_ref,
                links_by_source_ref,
            )
            for result in results
        ],
        "primary_objects": [
            _primary_object(result, object_by_source_ref)
            for result in results
            if result.source_ref in object_by_source_ref
        ],
        "related_objects": related_objects,
        "related_object_groups": _related_object_groups(related_objects),
        "entities": _entities(results, links_by_source_ref, object_by_source_ref),
        "unresolved_candidates": _unresolved_candidates(
            query=query,
            canonical_objects=canonical_objects,
            visible_source_refs=visible_source_refs,
        ),
        "limitations": _limitations(),
    }


def _summary(results: list[SearchResult]) -> str:
    if len(results) == 1:
        return "1 evidence item"
    return f"{len(results)} evidence items"


def _evidence_item(
    result: SearchResult,
    source: dict[str, object] | None,
    object_by_source_ref: dict[str, dict[str, object]],
    links_by_source_ref: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    context_object = object_by_source_ref.get(result.source_ref, {})
    record_type = "" if source is None else str(source["record_type"])
    return {
        "source_ref": result.source_ref,
        "source_url": "" if source is None else source["source_url"],
        "source_type": _source_type(record_type, context_object),
        "record_type": record_type,
        "source_system": "" if source is None else source["source_system"],
        "source_id": "" if source is None else source["source_id"],
        "canonical_object_type": context_object.get("object_type", ""),
        "title": result.subject,
        "snippet": result.snippet,
        "timestamp": result.date,
        "updated_timestamp": "" if source is None else source["updated_at"],
        "linked_entities": _entity_refs(links_by_source_ref.get(result.source_ref, [])),
        "permission_refs": [] if source is None else _json_list(source["permission_refs"]),
        "score": None,
        "why_included": "matched permission-filtered retrieval text",
    }


def _result_candidate(
    result: SearchResult,
    source: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "source_ref": result.source_ref,
        "title": result.subject,
        "snippet": result.snippet,
        "timestamp": result.date,
        "source_url": "" if source is None else source["source_url"],
        "record_type": "" if source is None else source["record_type"],
        "source_system": "" if source is None else source["source_system"],
        "source_id": "" if source is None else source["source_id"],
        "ranking_reason": "keyword match in permission-filtered retrieval unit",
        "score": None,
    }


def _primary_object(
    result: SearchResult,
    object_by_source_ref: dict[str, dict[str, object]],
) -> dict[str, object]:
    context_object = object_by_source_ref[result.source_ref]
    return {
        "object_ref": context_object["object_ref"],
        "object_type": context_object["object_type"],
        "title": result.subject,
        "source_refs": _json_list(context_object["source_refs"]),
        "why_primary": "matched evidence source",
        "confidence": 1.0,
    }


def _related_objects(
    *,
    results: list[SearchResult],
    source_records: list[dict[str, object]],
    object_by_source_ref: dict[str, dict[str, object]],
    entity_links: list[dict[str, object]],
    evidence_refs: set[str],
) -> list[dict[str, object]]:
    by_thread = _source_records_by_thread(source_records)
    links_by_source_ref = _links_by_source_ref(entity_links)
    related: list[dict[str, object]] = []
    seen: set[str] = set()
    for result in results:
        _add_linked_entity_related_objects(
            related=related,
            seen=seen,
            result=result,
            links=links_by_source_ref.get(result.source_ref, []),
            object_by_source_ref=object_by_source_ref,
        )
        primary_source = _source_record_for_ref(source_records, result.source_ref)
        if primary_source is None:
            continue
        _add_project_related_object(
            related=related,
            seen=seen,
            result=result,
            source=primary_source,
            object_by_source_ref=object_by_source_ref,
        )
        thread_ref = str(primary_source.get("thread_ref") or "")
        if not thread_ref:
            continue
        for candidate in by_thread.get(thread_ref, []):
            candidate_ref = str(candidate["source_ref"])
            if candidate_ref in evidence_refs or candidate_ref in seen:
                continue
            context_object = object_by_source_ref.get(candidate_ref)
            if context_object is None:
                continue
            related.append(
                {
                    "object_ref": context_object["object_ref"],
                    "object_type": context_object["object_type"],
                    "title": context_object["title"],
                    "relationship_to_primary": "same thread",
                    "relationship_source_refs": [result.source_ref, candidate_ref],
                    "confidence": 0.9,
                    "follow_up_hint": f"Ask about {context_object['title']}",
                }
            )
            seen.add(candidate_ref)
    return related[:5]


def _related_object_groups(
    related_objects: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {
        "people": [],
        "organizations": [],
        "work_items": [],
        "documents": [],
        "threads": [],
    }
    for related_object in related_objects:
        bucket = _related_object_bucket(related_object)
        if bucket:
            groups[bucket].append(related_object)
    return groups


def _related_object_bucket(related_object: dict[str, object]) -> str:
    relationship = str(related_object.get("relationship_to_primary") or "")
    if relationship == "same thread":
        return "threads"

    object_type = str(related_object.get("object_type") or "")
    if object_type == "Person":
        return "people"
    if object_type == "Organization":
        return "organizations"
    if object_type == "WorkItem":
        return "work_items"
    if object_type == "Document":
        return "documents"
    return ""


def _add_linked_entity_related_objects(
    *,
    related: list[dict[str, object]],
    seen: set[str],
    result: SearchResult,
    links: list[dict[str, object]],
    object_by_source_ref: dict[str, dict[str, object]],
) -> None:
    links_by_object_ref: dict[str, list[dict[str, object]]] = {}
    for link in links:
        object_ref = str(link["object_ref"])
        if object_ref == result.source_ref or object_ref in seen:
            continue
        links_by_object_ref.setdefault(object_ref, []).append(link)

    for object_ref, object_links in sorted(links_by_object_ref.items()):
        context_object = object_by_source_ref.get(object_ref)
        if context_object is None:
            continue
        relationship_types = sorted(
            {str(link["relationship_type"]) for link in object_links if link["relationship_type"]}
        )
        related.append(
            {
                "object_ref": context_object["object_ref"],
                "object_type": context_object["object_type"],
                "title": context_object["title"],
                "relationship_to_primary": f"linked entity: {', '.join(relationship_types)}",
                "relationship_source_refs": [result.source_ref],
                "confidence": max(float(link["confidence"]) for link in object_links),
                "follow_up_hint": f"Ask about {context_object['title']}",
            }
        )
        seen.add(object_ref)


def _add_project_related_object(
    *,
    related: list[dict[str, object]],
    seen: set[str],
    result: SearchResult,
    source: dict[str, object],
    object_by_source_ref: dict[str, dict[str, object]],
) -> None:
    metadata = _json_object(source.get("metadata_json"))
    project_id = metadata.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return
    source_system = str(source.get("source_system") or "")
    project_source_ref = f"{source_system}:project:{project_id}"
    if project_source_ref == result.source_ref or project_source_ref in seen:
        return
    context_object = object_by_source_ref.get(project_source_ref)
    if context_object is None:
        return
    related.append(
        {
            "object_ref": context_object["object_ref"],
            "object_type": context_object["object_type"],
            "title": context_object["title"],
            "relationship_to_primary": "same project",
            "relationship_source_refs": [result.source_ref, project_source_ref],
            "confidence": 0.85,
            "follow_up_hint": f"Ask about {context_object['title']}",
        }
    )
    seen.add(project_source_ref)


def _entities(
    results: list[SearchResult],
    links_by_source_ref: dict[str, list[dict[str, object]]],
    object_by_source_ref: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    entities_by_ref: dict[str, dict[str, object]] = {}
    for result in results:
        for link in links_by_source_ref.get(result.source_ref, []):
            entity_ref = _entity_ref(link)
            if not entity_ref:
                continue
            entity = entities_by_ref.setdefault(
                entity_ref,
                {
                    "entity_ref": entity_ref,
                    "object_ref": link["object_ref"],
                    "display_name": _display_name(link, object_by_source_ref),
                    "source_refs": [],
                    "relationship_types": [],
                    "confidence": link["confidence"],
                    "reason": link["reason"],
                    "status": link["status"],
                },
            )
            if result.source_ref not in entity["source_refs"]:
                entity["source_refs"].append(result.source_ref)
            if link["relationship_type"] not in entity["relationship_types"]:
                entity["relationship_types"].append(link["relationship_type"])
            entity["confidence"] = max(entity["confidence"], link["confidence"])
    return list(entities_by_ref.values())


def _unresolved_candidates(
    *,
    query: str,
    canonical_objects: list[dict[str, object]],
    visible_source_refs: set[str],
) -> list[dict[str, object]]:
    query_terms = set(_text_terms(query))
    query_text = " ".join(_text_terms(query))
    if not query_terms:
        return []

    people_by_first_name: dict[str, dict[str, dict[str, object]]] = {}
    first_names_with_full_match: set[str] = set()
    for context_object in canonical_objects:
        if context_object["object_type"] != "Person":
            continue
        if not set(_json_list(context_object["source_refs"])).intersection(visible_source_refs):
            continue
        display_name = str(context_object["title"])
        name_terms = _text_terms(display_name)
        if len(name_terms) < 2:
            continue
        first_name = name_terms[0]
        if " ".join(name_terms) in query_text:
            first_names_with_full_match.add(first_name)
            continue
        if first_name in query_terms:
            people_by_key = people_by_first_name.setdefault(first_name, {})
            key = _person_dedupe_key(context_object)
            people_by_key[key] = _preferred_person(people_by_key.get(key), context_object)

    candidates = []
    for matched_text, people_by_key in sorted(people_by_first_name.items()):
        if matched_text in first_names_with_full_match:
            continue
        people = list(people_by_key.values())
        if len(people) < 2:
            continue
        for person in sorted(people, key=lambda row: str(row["object_ref"])):
            candidates.append(
                {
                    "candidate_ref": f"candidate:person:{matched_text}:{person['object_ref']}",
                    "object_ref": person["object_ref"],
                    "object_type": "Person",
                    "display_name": person["title"],
                    "matched_text": matched_text,
                    "confidence": 0.5,
                    "reason": "ambiguous_visible_person_name",
                    "status": "unresolved",
                }
            )
    return candidates[:10]


def _person_dedupe_key(context_object: dict[str, object]) -> str:
    metadata = _json_object(context_object.get("metadata_json"))
    email = metadata.get("email")
    if isinstance(email, str) and email:
        return f"email:{email.casefold()}"
    return str(context_object["object_ref"])


def _preferred_person(
    current: dict[str, object] | None,
    candidate: dict[str, object],
) -> dict[str, object]:
    if current is None:
        return candidate
    return min([current, candidate], key=_person_preference_key)


def _person_preference_key(context_object: dict[str, object]) -> tuple[int, str]:
    metadata = _json_object(context_object.get("metadata_json"))
    source_system = metadata.get("source_system")
    source_priority = {"linear": 0, "twenty": 1, "slack": 2}
    return (source_priority.get(str(source_system), 99), str(context_object["object_ref"]))


def _links_by_source_ref(
    entity_links: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    by_source_ref: dict[str, list[dict[str, object]]] = {}
    for link in entity_links:
        by_source_ref.setdefault(str(link["source_ref"]), []).append(link)
    for links in by_source_ref.values():
        links.sort(key=lambda link: (str(link["relationship_type"]), str(link["object_ref"])))
    return by_source_ref


def _entity_refs(links: list[dict[str, object]]) -> list[str]:
    entity_refs = []
    for link in links:
        entity_ref = _entity_ref(link)
        if entity_ref and entity_ref not in entity_refs:
            entity_refs.append(entity_ref)
    return entity_refs


def _entity_ref(link: dict[str, object]) -> str:
    evidence = _json_object(link.get("evidence_json"))
    value = evidence.get("entity_ref")
    return value if isinstance(value, str) else ""


def _display_name(
    link: dict[str, object],
    object_by_source_ref: dict[str, dict[str, object]],
) -> str:
    context_object = object_by_source_ref.get(str(link["object_ref"]))
    if context_object is None:
        return ""
    return str(context_object["title"])


def _source_records_by_thread(
    source_records: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    by_thread: dict[str, list[dict[str, object]]] = {}
    for source_record in source_records:
        thread_ref = str(source_record.get("thread_ref") or "")
        if not thread_ref:
            continue
        by_thread.setdefault(thread_ref, []).append(source_record)
    for rows in by_thread.values():
        rows.sort(key=lambda row: (str(row.get("occurred_at") or ""), str(row["source_ref"])))
    return by_thread


def _source_record_for_ref(
    source_records: list[dict[str, object]],
    source_ref: str,
) -> dict[str, object] | None:
    for source_record in source_records:
        if source_record["source_ref"] == source_ref:
            return source_record
    return None


def _object_by_source_ref(
    canonical_objects: list[dict[str, object]],
    *,
    visible_source_refs: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    by_source_ref = {}
    for context_object in canonical_objects:
        for source_ref in _json_list(context_object["source_refs"]):
            if visible_source_refs is not None and source_ref not in visible_source_refs:
                continue
            by_source_ref[source_ref] = context_object
    return by_source_ref


def _json_list(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, str)]


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        return {}
    return decoded


def _source_type(record_type: str, context_object: dict[str, object]) -> str:
    if context_object.get("object_type"):
        return str(context_object["object_type"])
    return record_type


def _text_terms(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _limitations() -> list[str]:
    return ["related object expansion is limited to source-backed entity links and threads"]
