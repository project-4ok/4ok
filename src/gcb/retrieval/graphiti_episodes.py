from __future__ import annotations

import json
from typing import Any

from gcb.honcho.experiment import build_honcho_sync_plan


def graphiti_episodes_from_source_snapshot(
    data: dict[str, object],
    *,
    group_id: str = "gcb-internal",
) -> list[dict[str, object]]:
    plan = build_honcho_sync_plan(data)
    episodes: list[dict[str, object]] = []
    for message in plan.messages:
        source_ref = str(message.metadata["source_ref"])
        source = str(message.metadata["source"])
        episodes.append(
            {
                "uuid": _episode_uuid(source_ref),
                "group_id": group_id,
                "name": source_ref,
                "episode_body": _episode_body(
                    body=message.text,
                    source_ref=source_ref,
                    source_url=_optional_string(message.metadata.get("source_url")),
                    source_updated_at=_optional_string(message.metadata.get("source_updated_at")),
                    entities=_entities_from_metadata(message.metadata),
                    permission_refs=_string_list(message.metadata.get("permission_refs")),
                ),
                "source": "message",
                "source_description": f"{source} message",
                "reference_time": _optional_string(message.metadata.get("source_updated_at")),
                "metadata": {
                    "source": source,
                    "source_ref": source_ref,
                    "source_url": _optional_string(message.metadata.get("source_url")),
                    "source_updated_at": _optional_string(
                        message.metadata.get("source_updated_at")
                    ),
                    "entities": _entities_from_metadata(message.metadata),
                    "routing_confidence": message.metadata.get("routing_confidence"),
                    "routing_rule": message.metadata.get("routing_rule"),
                }
                | _permission_metadata(message.metadata),
            }
        )
    for source_ref, record in plan.source_imports.items():
        episodes.append(_catalog_episode(source_ref, record=record, group_id=group_id))
    return sorted(episodes, key=lambda item: str(item["name"]))


def _catalog_episode(
    source_ref: str,
    *,
    record: dict[str, str],
    group_id: str,
) -> dict[str, object]:
    source = record["source"]
    source_type = record["source_type"]
    return {
        "uuid": _episode_uuid(source_ref),
        "group_id": group_id,
        "name": source_ref,
        "episode_body": _episode_body(
            body=json.dumps(record, sort_keys=True),
            source_ref=source_ref,
            source_url=None,
            source_updated_at=None,
            entities=[record["entity_ref"]] if record.get("entity_ref") else [],
            permission_refs=[],
        ),
        "source": "json",
        "source_description": f"{source} {source_type}",
        "reference_time": None,
        "metadata": {
            "source": source,
            "source_ref": source_ref,
            "source_url": None,
            "source_updated_at": None,
            "entities": [record["entity_ref"]] if record.get("entity_ref") else [],
        },
    }


def _episode_uuid(source_ref: str) -> str:
    return f"gcb:graphiti:{source_ref}"


def _episode_body(
    *,
    body: str,
    source_ref: str,
    source_url: str | None,
    source_updated_at: str | None,
    entities: list[str],
    permission_refs: list[str],
) -> str:
    return (
        f"source_ref: {source_ref}\n"
        f"source_url: {source_url or ''}\n"
        f"source_updated_at: {source_updated_at or ''}\n"
        f"entities: {' '.join(entities)}\n"
        f"permission_refs: {' '.join(permission_refs)}\n"
        f"\n{body}"
    )


def _entities_from_metadata(metadata: dict[str, object]) -> list[str]:
    entities: list[str] = []
    for key in ("candidate_entities", "actors", "assignees", "employee_peer"):
        _extend_entities(entities, metadata.get(key))
    return entities


def _extend_entities(entities: list[str], value: object) -> None:
    if isinstance(value, str) and value.startswith("employee:") and value not in entities:
        entities.append(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.startswith("employee:") and item not in entities:
                entities.append(item)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _permission_metadata(metadata: dict[str, object]) -> dict[str, list[str]]:
    permission_refs = _string_list(metadata.get("permission_refs"))
    return {"permission_refs": permission_refs} if permission_refs else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
