import shutil
from pathlib import Path

import pytest

from fourok.runtime.connector_contracts import (
    CONNECTOR_TAP_CONTRACTS,
    ConnectorContractError,
    connector_contract_report,
    verify_connector_contract,
)


def test_connector_contract_report_proves_each_configured_fixture_tap() -> None:
    landing_root = Path(".local/test-artifacts/connector-contracts/report")
    shutil.rmtree(landing_root, ignore_errors=True)

    report = connector_contract_report(landing_root=landing_root)

    assert report["status"] == "ok"
    assert report["summary"] == {
        "total": 5,
        "failed": 0,
    }

    contracts = {contract["name"]: contract for contract in report["contracts"]}
    assert set(contracts) == {
        "gmail_fixture",
        "slack_fixture",
        "twenty_fixture",
        "linear_fixture",
        "google_drive_fixture",
    }

    assert contracts["slack_fixture"]["record_types"] == ["message"]
    assert contracts["twenty_fixture"]["record_types"] == ["organization", "person"]
    assert contracts["linear_fixture"]["record_types"] == ["message", "person", "work_item"]
    assert contracts["google_drive_fixture"]["record_types"] == ["document"]

    for contract in contracts.values():
        assert contract["status"] == "proved-with-fixture-tap"
        assert contract["record_count"] > 0
        assert contract["schema_messages"] > 0
        assert contract["state_messages"] > 0
        assert contract["checkpoint_keys"]
        assert contract["source_systems"]
        assert contract["source_refs"]


def test_connector_contract_proof_checks_failure_behavior() -> None:
    landing_root = Path(".local/test-artifacts/connector-contracts/failure")
    shutil.rmtree(landing_root, ignore_errors=True)
    bad_fixture = landing_root / "bad.jsonl"
    bad_fixture.parent.mkdir(parents=True)
    bad_fixture.write_text(
        '{"type":"SCHEMA","stream":"slack_messages","schema":{}}\n'
        '{"type":"RECORD","stream":"slack_messages","record":{"text":"missing ids"}}\n',
        encoding="utf-8",
    )
    contract = next(
        contract for contract in CONNECTOR_TAP_CONTRACTS if contract.name == "slack_fixture"
    )

    with pytest.raises(ConnectorContractError, match="requires channel_id and ts"):
        verify_connector_contract(
            contract.with_fixture_path(bad_fixture),
            landing_root=landing_root / "landing",
        )
