from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fourok.honcho.catalog import CatalogEmployee


@dataclass
class HonchoSyncState:
    path: Path
    source_refs: dict[str, dict[str, str]] = field(default_factory=dict)
    checkpoints: dict[str, str] = field(default_factory=dict)
    employees: dict[str, CatalogEmployee] = field(default_factory=dict)
    linear_teams: dict[str, dict[str, str]] = field(default_factory=dict)
    linear_projects: dict[str, dict[str, str]] = field(default_factory=dict)
    source_imports: dict[str, dict[str, str]] = field(default_factory=dict)
    last_successful_syncs: dict[str, str] = field(default_factory=dict)
    catalog_updated_at_values: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> HonchoSyncState:
        if not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Honcho sync state JSON: {path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"invalid Honcho sync state shape: {path}")
        return cls(
            path=path,
            source_refs=_string_mapping_dict(data.get("source_refs")),
            checkpoints=_string_dict(data.get("checkpoints")),
            employees=_employee_dict(data.get("employees")),
            linear_teams=_string_mapping_dict(data.get("linear_teams")),
            linear_projects=_string_mapping_dict(data.get("linear_projects")),
            source_imports=_string_mapping_dict(data.get("source_imports")),
            last_successful_syncs=_string_dict(data.get("last_successful_syncs")),
            catalog_updated_at_values=_string_dict(data.get("catalog_updated_at")),
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    def record_write_receipt(
        self,
        *,
        source_ref: str,
        honcho_message_id: str,
        honcho_peer_id: str,
        honcho_session_id: str,
        rule_version: str,
        routing_confidence: str,
        employee_peer: str,
        candidate_entities: str,
        aggregate_fallback_peer: str,
        source_url: str,
        source_updated_at: str,
        written_at: str,
        supersedes_honcho_message_id: str = "",
        supersedes_source_updated_at: str = "",
    ) -> None:
        receipt = {
            "honcho_message_id": honcho_message_id,
            "honcho_peer_id": honcho_peer_id,
            "honcho_session_id": honcho_session_id,
            "rule_version": rule_version,
            "routing_confidence": routing_confidence,
            "employee_peer": employee_peer,
            "candidate_entities": candidate_entities,
            "aggregate_fallback_peer": aggregate_fallback_peer,
            "source_url": source_url,
            "source_updated_at": source_updated_at,
            "written_at": written_at,
        }
        if supersedes_honcho_message_id:
            receipt["supersedes_honcho_message_id"] = supersedes_honcho_message_id
        if supersedes_source_updated_at:
            receipt["supersedes_source_updated_at"] = supersedes_source_updated_at
        self.source_refs[source_ref] = receipt

    def is_imported(self, source_ref: str) -> bool:
        return source_ref in self.source_refs

    def imported_source_refs(self) -> list[str]:
        return sorted(self.source_refs)

    def source_receipt(self, source_ref: str) -> dict[str, str] | None:
        receipt = self.source_refs.get(source_ref)
        if receipt is None:
            return None
        return dict(receipt)

    def set_checkpoint(self, connector_name: str, checkpoint: str) -> None:
        self.checkpoints[connector_name] = checkpoint

    def connector_checkpoint(self, connector_name: str) -> str | None:
        return self.checkpoints.get(connector_name)

    def record_successful_sync(self, connector_name: str, synced_at: str) -> None:
        self.last_successful_syncs[connector_name] = synced_at

    def last_successful_sync(self, connector_name: str) -> str | None:
        return self.last_successful_syncs.get(connector_name)

    def set_catalog_updated_at(self, catalog_name: str, updated_at: str) -> None:
        self.catalog_updated_at_values[catalog_name] = updated_at

    def catalog_updated_at(self, catalog_name: str) -> str | None:
        return self.catalog_updated_at_values.get(catalog_name)

    def record_employee_catalog(self, employees: dict[str, CatalogEmployee]) -> None:
        self.employees = {
            key: CatalogEmployee(
                entity_ref=employee.entity_ref,
                display_name=employee.display_name,
                primary_email=employee.primary_email,
                honcho_peer_id=employee.honcho_peer_id,
                source_identities=list(employee.source_identities),
            )
            for key, employee in employees.items()
        }

    def record_linear_catalogs(
        self,
        *,
        teams: dict[str, dict[str, object]],
        projects: dict[str, dict[str, object]],
    ) -> None:
        self.linear_teams = _string_mapping_dict(teams)
        self.linear_projects = _string_mapping_dict(projects)

    def record_source_imports(
        self,
        source_imports: dict[str, dict[str, str]],
        *,
        imported_at: str,
    ) -> None:
        self.source_imports = {
            source_ref: {**record, "imported_at": imported_at}
            for source_ref, record in sorted(source_imports.items())
        }

    def employee_catalog(self) -> dict[str, CatalogEmployee]:
        return {
            key: CatalogEmployee(
                entity_ref=employee.entity_ref,
                display_name=employee.display_name,
                primary_email=employee.primary_email,
                honcho_peer_id=employee.honcho_peer_id,
                source_identities=list(employee.source_identities),
            )
            for key, employee in self.employees.items()
        }

    def classify_source_refs(self, source_refs: list[str]) -> dict[str, list[str]]:
        return {
            "new_source_refs": [
                source_ref for source_ref in source_refs if not self.is_imported(source_ref)
            ],
            "skipped_source_refs": [
                source_ref for source_ref in source_refs if self.is_imported(source_ref)
            ],
        }

    def classify_message_source_refs(
        self, messages: list[dict[str, object]]
    ) -> dict[str, list[str]]:
        new_source_refs: list[str] = []
        changed_source_refs: list[str] = []
        skipped_source_refs: list[str] = []

        for message in messages:
            source_ref = message.get("source_ref")
            if not isinstance(source_ref, str) or not source_ref:
                continue
            existing = self.source_refs.get(source_ref)
            if existing is None:
                new_source_refs.append(source_ref)
                continue
            if _is_newer_timestamp(message.get("source_updated_at"), existing):
                changed_source_refs.append(source_ref)
                continue
            skipped_source_refs.append(source_ref)

        return {
            "new_source_refs": new_source_refs,
            "changed_source_refs": changed_source_refs,
            "skipped_source_refs": skipped_source_refs,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "source_refs": self.source_refs,
            "checkpoints": self.checkpoints,
            "employees": {
                key: employee.to_dict() for key, employee in sorted(self.employees.items())
            },
            "linear_teams": self.linear_teams,
            "linear_projects": self.linear_projects,
            "source_imports": self.source_imports,
            "last_successful_syncs": self.last_successful_syncs,
            "catalog_updated_at": self.catalog_updated_at_values,
        }


def _string_mapping_dict(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, nested in value.items():
        if isinstance(key, str):
            result[key] = _string_dict(nested)
    return result


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: nested_value
        for key, nested_value in value.items()
        if isinstance(key, str) and isinstance(nested_value, str)
    }


def _employee_dict(value: object) -> dict[str, CatalogEmployee]:
    if not isinstance(value, dict):
        return {}
    employees: dict[str, CatalogEmployee] = {}
    for key, employee_data in value.items():
        if not isinstance(key, str) or not isinstance(employee_data, dict):
            continue
        employee = _employee_from_dict(employee_data)
        if employee is not None:
            employees[key] = employee
    return employees


def _employee_from_dict(value: dict[object, object]) -> CatalogEmployee | None:
    entity_ref = value.get("entity_ref")
    display_name = value.get("display_name")
    primary_email = value.get("primary_email")
    honcho_peer_id = value.get("honcho_peer_id")
    source_identities = value.get("source_identities")
    if not isinstance(entity_ref, str) or not isinstance(primary_email, str):
        return None
    return CatalogEmployee(
        entity_ref=entity_ref,
        display_name=display_name if isinstance(display_name, str) else primary_email,
        primary_email=primary_email,
        honcho_peer_id=honcho_peer_id if isinstance(honcho_peer_id, str) else None,
        source_identities=[identity for identity in source_identities if isinstance(identity, str)]
        if isinstance(source_identities, list)
        else [],
    )


def _is_newer_timestamp(incoming_updated_at: object, existing: dict[str, str]) -> bool:
    if not isinstance(incoming_updated_at, str) or not incoming_updated_at:
        return False
    existing_updated_at = existing.get("source_updated_at")
    if not existing_updated_at:
        return False
    incoming = _parse_iso_datetime(incoming_updated_at)
    stored = _parse_iso_datetime(existing_updated_at)
    if incoming is None or stored is None:
        return False
    return incoming > stored


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
