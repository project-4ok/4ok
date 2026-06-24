from pathlib import Path

import pytest

from gcb.etl.extract.connectors import (
    land_singer_records,
    load_landed_source_records,
    load_twenty_source_records,
    twenty_person_source_record_from_raw,
)
from gcb.etl.extract.twenty_tap import TwentyTapConfig, run_twenty_tap

FIXTURES = Path(__file__).parents[3] / "fixtures" / "connectors"
SINGER_TWENTY_CRM = FIXTURES / "singer_twenty_crm.jsonl"


def test_twenty_singer_records_map_to_source_records() -> None:
    source_records = load_twenty_source_records(SINGER_TWENTY_CRM)

    assert [record.source_ref for record in source_records] == [
        "twenty:company:company-alpha",
        "twenty:person:person-robin",
    ]
    assert [record.record_type for record in source_records] == ["organization", "person"]
    assert source_records[0].title == "Alpha Hausverwaltung"
    assert source_records[0].body == "Alpha Hausverwaltung alpha.example"
    assert source_records[0].source_url.endswith("/company-alpha")
    assert source_records[0].metadata == {
        "domain": "alpha.example",
        "source_object_type": "company",
    }
    assert source_records[1].title == "Robin Scharf"
    assert source_records[1].body == (
        "Robin Scharf Operations Lead Alpha Hausverwaltung robin.alpha@example.com"
    )
    assert source_records[1].identity_refs == ("twenty:email:robin.alpha@example.com",)
    assert source_records[1].metadata == {
        "company_id": "company-alpha",
        "company_name": "Alpha Hausverwaltung",
        "job_title": "Operations Lead",
        "source_object_type": "person",
    }


def test_twenty_raw_landing_can_be_reloaded_into_source_records() -> None:
    landing_dir = Path(".local/test-artifacts/connectors/twenty-raw-landing")
    if landing_dir.exists():
        for path in landing_dir.glob("*"):
            path.unlink()

    report = land_singer_records(SINGER_TWENTY_CRM, landing_dir)
    companies = load_landed_source_records(landing_dir, stream="twenty_companies")
    people = load_landed_source_records(landing_dir, stream="twenty_people")

    assert report.record_count == 2
    assert report.streams == {"twenty_companies": 1, "twenty_people": 1}
    assert report.schema_messages == 2
    assert report.state_messages == 1
    assert companies[0].source_ref == "twenty:company:company-alpha"
    assert people[0].source_ref == "twenty:person:person-robin"


def test_twenty_person_adapter_rejects_missing_id_before_source_records() -> None:
    with pytest.raises(ValueError, match="Twenty person record requires id"):
        twenty_person_source_record_from_raw({"name": {"firstName": "Robin"}})


def test_committed_meltano_config_wires_twenty_fixture_job() -> None:
    config = (Path(__file__).parents[3] / "meltano.yml").read_text(encoding="utf-8")

    assert "tap-gcb-twenty-fixture" in config
    assert "fixtures/connectors/singer_twenty_crm.jsonl" in config
    assert "singer-twenty-fixture-to-raw" in config
    assert "tap-gcb-twenty-fixture target-gcb-raw-jsonl" in config


def test_twenty_tap_emits_companies_people_and_state() -> None:
    calls: list[dict[str, object]] = []

    def fake_rest(path: str, params: dict[str, object]) -> dict[str, object]:
        calls.append({"path": path, "params": params})
        if path == "companies":
            return {
                "data": {
                    "companies": [
                        {
                            "id": "company-alpha",
                            "name": "Alpha Hausverwaltung",
                            "domainName": "alpha.example",
                            "createdAt": "2026-06-01T08:00:00Z",
                            "updatedAt": "2026-06-02T09:00:00Z",
                        }
                    ]
                }
            }
        if path == "people":
            return {
                "data": {
                    "people": [
                        {
                            "id": "person-robin",
                            "name": {"firstName": "Robin", "lastName": "Scharf"},
                            "emails": {"primaryEmail": "robin.alpha@example.com"},
                            "jobTitle": "Operations Lead",
                            "company": {
                                "id": "company-alpha",
                                "name": "Alpha Hausverwaltung",
                            },
                            "createdAt": "2026-06-01T08:05:00Z",
                            "updatedAt": "2026-06-02T09:05:00Z",
                        }
                    ]
                }
            }
        raise AssertionError(path)

    messages = run_twenty_tap(
        TwentyTapConfig(api_key="secret", base_url="https://twenty.example/rest", limit=5),
        rest=fake_rest,
    )

    assert [message["type"] for message in messages] == [
        "SCHEMA",
        "RECORD",
        "SCHEMA",
        "RECORD",
        "STATE",
    ]
    assert [message.get("stream") for message in messages if message["type"] == "RECORD"] == [
        "twenty_companies",
        "twenty_people",
    ]
    assert messages[-1] == {
        "type": "STATE",
        "value": {
            "bookmarks": {
                "twenty_companies": {"updated_at": "2026-06-02T09:00:00Z"},
                "twenty_people": {"updated_at": "2026-06-02T09:05:00Z"},
            }
        },
    }
    assert calls == [
        {"path": "companies", "params": {"limit": 5}},
        {"path": "people", "params": {"limit": 5}},
    ]


def test_twenty_tap_paginates_companies_and_people_until_configured_limit() -> None:
    calls: list[dict[str, object]] = []

    def page(
        key: str,
        id_prefix: str,
        start: int,
        count: int,
        *,
        has_next: bool,
    ) -> dict[str, object]:
        rows = [
            {"id": f"{id_prefix}-{index}", "name": f"{id_prefix.title()} {index}"}
            for index in range(start, start + count)
        ]
        return {
            "data": {key: rows},
            "totalCount": 450,
            "pageInfo": {
                "endCursor": f"cursor-{id_prefix}-{start + count - 1}",
                "hasNextPage": has_next,
            },
        }

    def fake_rest(path: str, params: dict[str, object]) -> dict[str, object]:
        calls.append({"path": path, "params": dict(params)})
        if path == "companies":
            if params == {"limit": 200}:
                return page("companies", "company", 0, 200, has_next=True)
            if params == {"limit": 200, "starting_after": "cursor-company-199"}:
                return page("companies", "company", 200, 200, has_next=True)
            if params == {"limit": 50, "starting_after": "cursor-company-399"}:
                return page("companies", "company", 400, 50, has_next=True)
        if path == "people":
            if params == {"limit": 200}:
                return page("people", "person", 0, 200, has_next=True)
            if params == {"limit": 200, "starting_after": "cursor-person-199"}:
                return page("people", "person", 200, 200, has_next=True)
            if params == {"limit": 50, "starting_after": "cursor-person-399"}:
                return page("people", "person", 400, 50, has_next=True)
        raise AssertionError((path, params))

    messages = run_twenty_tap(
        TwentyTapConfig(api_key="secret", base_url="https://twenty.example/rest", limit=450),
        rest=fake_rest,
    )

    assert sum(1 for message in messages if message.get("stream") == "twenty_companies") == 451
    assert sum(1 for message in messages if message.get("stream") == "twenty_people") == 451
    assert calls == [
        {"path": "companies", "params": {"limit": 200}},
        {"path": "companies", "params": {"limit": 200, "starting_after": "cursor-company-199"}},
        {"path": "companies", "params": {"limit": 50, "starting_after": "cursor-company-399"}},
        {"path": "people", "params": {"limit": 200}},
        {"path": "people", "params": {"limit": 200, "starting_after": "cursor-person-199"}},
        {"path": "people", "params": {"limit": 50, "starting_after": "cursor-person-399"}},
    ]


def test_twenty_tap_output_feeds_existing_source_record_adapter(tmp_path: Path) -> None:
    def fake_rest(path: str, params: dict[str, object]) -> dict[str, object]:
        if path == "companies":
            return {"data": {"companies": [{"id": "company-alpha", "name": "Alpha"}]}}
        if path == "people":
            return {
                "data": {
                    "people": [
                        {
                            "id": "person-robin",
                            "name": {"firstName": "Robin", "lastName": "Scharf"},
                            "email": "robin.alpha@example.com",
                            "company_id": "company-alpha",
                            "company_name": "Alpha",
                        }
                    ]
                }
            }
        raise AssertionError(path)

    messages = run_twenty_tap(
        TwentyTapConfig(api_key="secret", base_url="https://twenty.example/rest", limit=5),
        rest=fake_rest,
    )
    singer_file = tmp_path / "twenty.singer.jsonl"
    singer_file.write_text(
        "\n".join(__import__("json").dumps(message, sort_keys=True) for message in messages) + "\n",
        encoding="utf-8",
    )

    records = load_twenty_source_records(singer_file)

    assert [record.source_ref for record in records] == [
        "twenty:company:company-alpha",
        "twenty:person:person-robin",
    ]
    assert records[1].identity_refs == ("twenty:email:robin.alpha@example.com",)


def test_twenty_tap_requires_api_key() -> None:
    with pytest.raises(ValueError, match="TWENTY_API_KEY is required"):
        TwentyTapConfig(api_key="", base_url="https://twenty.example/rest")
