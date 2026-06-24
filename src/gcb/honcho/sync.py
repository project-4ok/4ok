from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from gcb.honcho.experiment import HonchoMessagePlan, HonchoSyncPlan
from gcb.honcho.state import HonchoSyncState


class HonchoWriter(Protocol):
    def add_message(self, message: HonchoMessagePlan) -> object: ...

    def update_message_metadata(
        self,
        *,
        session_id: str,
        message_id: str,
        metadata: dict[str, object],
    ) -> object: ...


def execute_honcho_sync(
    plan: HonchoSyncPlan,
    *,
    state: HonchoSyncState,
    client: HonchoWriter,
    synced_at: str | None = None,
) -> dict[str, object]:
    sync_timestamp = synced_at or _now_iso()
    written_source_refs: list[str] = []
    changed_source_refs: list[str] = []
    skipped_source_refs: list[str] = []

    for message in plan.messages:
        source_ref = _source_ref(message)
        existing_receipt: dict[str, str] | None = None
        if state.is_imported(source_ref):
            existing_receipt = state.source_receipt(source_ref)
            if not state.classify_message_source_refs([_message_source_state(message)])[
                "changed_source_refs"
            ]:
                skipped_source_refs.append(source_ref)
                continue
            changed_source_refs.append(source_ref)
            message = _superseding_message(message, existing_receipt=existing_receipt)

        response = client.add_message(message)
        honcho_message_id = _message_id(response)
        state.record_write_receipt(
            source_ref=source_ref,
            honcho_message_id=honcho_message_id,
            honcho_peer_id=message.peer,
            honcho_session_id=message.session,
            rule_version=str(message.metadata.get("routing_rule") or ""),
            routing_confidence=str(message.metadata.get("routing_confidence") or ""),
            employee_peer=str(message.metadata.get("employee_peer") or ""),
            candidate_entities=_candidate_entities_receipt(message),
            aggregate_fallback_peer=str(message.metadata.get("aggregate_fallback_peer") or ""),
            source_url=str(message.metadata.get("source_url") or ""),
            source_updated_at=str(message.metadata.get("source_updated_at") or ""),
            written_at=sync_timestamp,
            supersedes_honcho_message_id=str(
                message.metadata.get("supersedes_honcho_message_id") or ""
            ),
            supersedes_source_updated_at=str(
                message.metadata.get("supersedes_source_updated_at") or ""
            ),
        )
        state.save()
        if source_ref in changed_source_refs and existing_receipt is not None:
            _mark_superseded(
                client,
                source_ref=source_ref,
                existing_receipt=existing_receipt,
                replacement_message_id=honcho_message_id,
                replacement_source_updated_at=str(message.metadata.get("source_updated_at") or ""),
            )
        written_source_refs.append(source_ref)

    _advance_linear_checkpoint(plan, state=state)
    state.record_employee_catalog(plan.employees)
    state.record_linear_catalogs(teams=plan.linear_teams, projects=plan.linear_projects)
    state.record_source_imports(plan.source_imports, imported_at=sync_timestamp)
    _record_successful_sync_metadata(plan, state=state, synced_at=sync_timestamp)
    state.save()
    return {
        "status": "ok",
        "summary": plan.summary,
        "written_source_refs": written_source_refs,
        "changed_source_refs": changed_source_refs,
        "skipped_source_refs": skipped_source_refs,
        "written_messages": len(written_source_refs),
        "skipped_messages": len(skipped_source_refs),
    }


def _source_ref(message: HonchoMessagePlan) -> str:
    source_ref = message.metadata.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        raise ValueError("Honcho message is missing metadata.source_ref")
    return source_ref


def _message_source_state(message: HonchoMessagePlan) -> dict[str, object]:
    return {
        "source_ref": message.metadata.get("source_ref"),
        "source_updated_at": message.metadata.get("source_updated_at"),
    }


def _superseding_message(
    message: HonchoMessagePlan,
    *,
    existing_receipt: dict[str, str] | None,
) -> HonchoMessagePlan:
    metadata = dict(message.metadata)
    metadata["source_change"] = "changed"
    if existing_receipt is not None:
        metadata["supersedes_honcho_message_id"] = existing_receipt.get("honcho_message_id", "")
        metadata["supersedes_source_updated_at"] = existing_receipt.get("source_updated_at", "")
    return replace(message, metadata=metadata)


def _mark_superseded(
    client: HonchoWriter,
    *,
    source_ref: str,
    existing_receipt: dict[str, str],
    replacement_message_id: str,
    replacement_source_updated_at: str,
) -> None:
    message_id = existing_receipt.get("honcho_message_id")
    session_id = existing_receipt.get("honcho_session_id")
    if not message_id or not session_id:
        return
    client.update_message_metadata(
        session_id=session_id,
        message_id=message_id,
        metadata={
            "source_ref": source_ref,
            "source_status": "superseded",
            "source_updated_at": existing_receipt.get("source_updated_at", ""),
            "superseded_by_honcho_message_id": replacement_message_id,
            "superseded_by_source_updated_at": replacement_source_updated_at,
        },
    )


def _candidate_entities_receipt(message: HonchoMessagePlan) -> str:
    value = message.metadata.get("candidate_entities")
    if not isinstance(value, list):
        return ""
    return ",".join(item for item in value if isinstance(item, str))


def _message_id(response: object) -> str:
    if isinstance(response, list) and response and isinstance(response[0], dict):
        message_id = response[0].get("id")
        if isinstance(message_id, str):
            return message_id
    if isinstance(response, dict):
        message_id = response.get("id")
        if isinstance(message_id, str):
            return message_id
    return ""


def _advance_linear_checkpoint(plan: HonchoSyncPlan, *, state: HonchoSyncState) -> None:
    updated_at_values = [
        value
        for message in plan.messages
        if message.metadata.get("source") == "linear"
        for value in [message.metadata.get("source_updated_at")]
        if isinstance(value, str) and value
    ]
    if updated_at_values:
        state.set_checkpoint("linear", max(updated_at_values))


def _record_successful_sync_metadata(
    plan: HonchoSyncPlan,
    *,
    state: HonchoSyncState,
    synced_at: str,
) -> None:
    for source in plan.source_names:
        state.record_successful_sync(source, synced_at)
    state.set_catalog_updated_at("employees", synced_at)
    if plan.linear_teams:
        state.set_catalog_updated_at("linear_teams", synced_at)
    if plan.linear_projects:
        state.set_catalog_updated_at("linear_projects", synced_at)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
