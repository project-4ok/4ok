from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fourok.etl.extract.connectors import (
    ConnectorPayloadError,
    land_singer_records,
    load_landed_source_records,
)


class ConnectorContractError(RuntimeError):
    """Connector output failed the source-record boundary contract."""


@dataclass(frozen=True)
class ConnectorTapContract:
    name: str
    source: str
    tap_name: str
    job_name: str
    fixture_path: Path
    streams: tuple[str, ...]
    required_checkpoint_keys: tuple[str, ...]
    credential_env: tuple[str, ...] = ()
    status: str = "proved-with-fixture-tap"

    def with_fixture_path(self, fixture_path: Path) -> ConnectorTapContract:
        return replace(self, fixture_path=fixture_path)


@dataclass(frozen=True)
class ConnectorContractResult:
    contract: ConnectorTapContract
    record_count: int
    schema_messages: int
    state_messages: int
    streams: dict[str, int]
    checkpoint_keys: tuple[str, ...]
    source_systems: tuple[str, ...]
    record_types: tuple[str, ...]
    source_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.contract.name,
            "source": self.contract.source,
            "tap_name": self.contract.tap_name,
            "job_name": self.contract.job_name,
            "status": self.contract.status,
            "fixture_path": str(self.contract.fixture_path),
            "streams": self.streams,
            "record_count": self.record_count,
            "schema_messages": self.schema_messages,
            "state_messages": self.state_messages,
            "checkpoint_keys": list(self.checkpoint_keys),
            "credential_env": list(self.contract.credential_env),
            "source_systems": list(self.source_systems),
            "record_types": list(self.record_types),
            "source_refs": list(self.source_refs),
        }


CONNECTOR_TAP_CONTRACTS = (
    ConnectorTapContract(
        name="gmail_fixture",
        source="gmail",
        tap_name="tap-fourok-fixture",
        job_name="singer-fixture-to-raw",
        fixture_path=Path("tests/fixtures/connectors/singer_email_messages.jsonl"),
        streams=("email_messages",),
        required_checkpoint_keys=("bookmarks",),
    ),
    ConnectorTapContract(
        name="slack_fixture",
        source="slack",
        tap_name="tap-fourok-slack-fixture",
        job_name="singer-slack-fixture-to-raw",
        fixture_path=Path("tests/fixtures/connectors/singer_slack_messages.jsonl"),
        streams=("slack_messages",),
        required_checkpoint_keys=("bookmarks",),
        credential_env=("SLACK_BOT_TOKEN",),
    ),
    ConnectorTapContract(
        name="twenty_fixture",
        source="twenty",
        tap_name="tap-fourok-twenty-fixture",
        job_name="singer-twenty-fixture-to-raw",
        fixture_path=Path("tests/fixtures/connectors/singer_twenty_crm.jsonl"),
        streams=("twenty_companies", "twenty_people"),
        required_checkpoint_keys=("bookmarks",),
        credential_env=("TWENTY_API_KEY", "TWENTY_BASE_URL"),
    ),
    ConnectorTapContract(
        name="linear_fixture",
        source="linear",
        tap_name="tap-fourok-linear-fixture",
        job_name="singer-linear-fixture-to-raw",
        fixture_path=Path("tests/fixtures/connectors/singer_linear_work_items.jsonl"),
        streams=("linear_users", "linear_issues", "linear_comments"),
        required_checkpoint_keys=("bookmarks",),
        credential_env=("LINEAR_API_KEY",),
    ),
    ConnectorTapContract(
        name="google_drive_fixture",
        source="google_drive",
        tap_name="tap-fourok-google-drive-fixture",
        job_name="singer-google-drive-fixture-to-raw",
        fixture_path=Path("tests/fixtures/connectors/singer_google_drive_docs.jsonl"),
        streams=("google_drive_files",),
        required_checkpoint_keys=("bookmarks",),
        credential_env=("GOOGLE_APPLICATION_CREDENTIALS",),
    ),
)


def connector_contract_report(
    *,
    landing_root: Path = Path(".local/connector-contracts"),
    contracts: tuple[ConnectorTapContract, ...] = CONNECTOR_TAP_CONTRACTS,
) -> dict[str, Any]:
    results = []
    failures = []
    for contract in contracts:
        try:
            results.append(verify_connector_contract(contract, landing_root=landing_root).to_dict())
        except ConnectorContractError as exc:
            failures.append({"name": contract.name, "error": str(exc)})

    return {
        "status": "ok" if not failures else "failed",
        "summary": {
            "total": len(contracts),
            "failed": len(failures),
        },
        "contracts": results,
        "failures": failures,
    }


def verify_connector_contract(
    contract: ConnectorTapContract,
    *,
    landing_root: Path = Path(".local/connector-contracts"),
) -> ConnectorContractResult:
    landing_dir = landing_root / contract.name
    if landing_dir.exists():
        for child in landing_dir.iterdir():
            if child.is_file():
                child.unlink()
    landing_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = land_singer_records(contract.fixture_path, landing_dir)
        source_records = [
            record
            for stream in contract.streams
            for record in load_landed_source_records(landing_dir, stream=stream)
        ]
    except (ValueError, ConnectorPayloadError) as exc:
        raise ConnectorContractError(str(exc)) from exc

    if report.record_count <= 0:
        raise ConnectorContractError(f"{contract.name} produced no records")
    if report.schema_messages <= 0:
        raise ConnectorContractError(f"{contract.name} produced no schema messages")
    if report.state_messages <= 0:
        raise ConnectorContractError(f"{contract.name} produced no state messages")
    if not source_records:
        raise ConnectorContractError(f"{contract.name} produced no SourceRecords")

    missing_streams = [stream for stream in contract.streams if stream not in report.streams]
    if missing_streams:
        raise ConnectorContractError(
            f"{contract.name} missing required streams: {', '.join(missing_streams)}"
        )

    checkpoint_keys = tuple(sorted((report.latest_state or {}).keys()))
    missing_checkpoint_keys = [
        key for key in contract.required_checkpoint_keys if key not in checkpoint_keys
    ]
    if missing_checkpoint_keys:
        raise ConnectorContractError(
            f"{contract.name} missing checkpoint keys: {', '.join(missing_checkpoint_keys)}"
        )

    return ConnectorContractResult(
        contract=contract,
        record_count=report.record_count,
        schema_messages=report.schema_messages,
        state_messages=report.state_messages,
        streams=report.streams,
        checkpoint_keys=checkpoint_keys,
        source_systems=tuple(sorted({record.source_system for record in source_records})),
        record_types=tuple(sorted({record.record_type for record in source_records})),
        source_refs=tuple(sorted(record.source_ref for record in source_records)),
    )
