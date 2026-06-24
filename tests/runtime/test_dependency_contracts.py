from gcb.runtime.dependency_contracts import (
    DEPENDENCY_CONTRACTS,
    REQUIRED_DIMENSIONS,
    dependency_contract_report,
)


def test_dependency_contracts_cover_required_spike_dimensions() -> None:
    report = dependency_contract_report()

    assert report["status"] == "ok"
    assert report["summary"]["missing_dimension_count"] == 0
    assert report["summary"]["unproved_count"] == 0
    assert report["required_dimensions"] == list(REQUIRED_DIMENSIONS)

    contracts = {contract["name"]: contract for contract in report["contracts"]}
    assert {
        "docker-compose-runtime",
        "google-drive-live-custom-singer-tap",
        "postgresql",
        "infisical-sdk",
        "singer-meltano-style-connectors",
        "configured-singer-taps",
        "linear-live-custom-singer-tap",
        "slack-live-singer-tap",
        "twenty-live-custom-singer-tap",
        "pypdf",
        "opentelemetry-lgtm",
        "openclaw-plugin-boundary",
        "cerbos",
    } <= set(contracts)

    for contract in contracts.values():
        assert contract["proof_commands"]
        assert contract["dimensions"] == list(REQUIRED_DIMENSIONS)
        assert contract["missing_dimensions"] == []


def test_dependency_contract_registry_has_no_duplicate_names() -> None:
    names = [contract.name for contract in DEPENDENCY_CONTRACTS]

    assert len(names) == len(set(names))
