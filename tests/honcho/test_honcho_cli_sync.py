import json
from pathlib import Path
from urllib.error import URLError

from gcb.cli import main

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures" / "honcho" / "linear_twenty_slack_sample.json"
)
CONTEXT_SUBSTRATE_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "context_substrate"
    / "source_snapshot_eval.json"
)
CONTEXT_SUBSTRATE_CASES = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "context_substrate"
    / "context_substrate_cases.json"
)


class _FakeHonchoHttpClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def add_message(self, message):
        return [{"id": "msg-1"}]


def test_cli_honcho_receipt_reports_missing_source_ref(capsys, monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state_path.write_text('{"source_refs":{}}', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-receipt",
            "linear:issue:missing",
            "--state",
            str(state_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "source_ref": "linear:issue:missing",
        "receipt": None,
    }


def test_cli_honcho_sync_uses_persisted_employee_catalog_for_planning(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    fixture_path = tmp_path / "linear-slack-only.json"
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["twenty_workspace_members"] = []
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    state_path = tmp_path / "honcho-sync-state.json"
    state_path.write_text(
        json.dumps(
            {
                "source_refs": {},
                "checkpoints": {},
                "employees": {
                    "employee:email:olivia@example.com": {
                        "entity_ref": "employee:email:olivia@example.com",
                        "display_name": "Olivia Smith",
                        "primary_email": "olivia@example.com",
                        "honcho_peer_id": None,
                        "source_identities": [
                            "twenty:workspaceMember:twenty-member-olivia",
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--dry-run",
            "--fixture",
            str(fixture_path),
            "--state",
            str(state_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["messages"][0]["peer"] == "slack_U123456"
    assert output["messages"][0]["metadata"]["employee_peer"] == (
        "employee:email:olivia@example.com"
    )


def test_cli_honcho_sync_live_sources_passes_state_checkpoint_with_overlap(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state_path.write_text(
        '{"source_refs":{},"checkpoints":{"linear":"2026-06-01T10:15:00+00:00"}}',
        encoding="utf-8",
    )

    def fake_fetch(config, **kwargs):
        return {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        }

    def fake_collect(secrets, *, limit, catalog_limit, sources, checkpoints, overlap_minutes):
        assert limit == 20
        assert catalog_limit == 100
        assert checkpoints == {"linear": "2026-06-01T10:15:00+00:00"}
        assert overlap_minutes == 10
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.fetch_infisical_secrets", fake_fetch)
    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.collect_source_snapshot", fake_collect)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--dry-run",
            "--summary-only",
            "--live-sources",
            "--state",
            str(state_path),
            "--checkpoint-overlap-minutes",
            "10",
            "--infisical-project-id",
            "project-123",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["honcho_messages"] == 1


def test_cli_honcho_sync_write_persists_receipts(capsys, monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"

    class FakeHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def add_message(self, message):
            return [{"id": "msg-1"}]

    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.HonchoHttpClient", FakeHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--write",
            "--fixture",
            str(FIXTURE),
            "--state",
            str(state_path),
            "--honcho-url",
            "http://honcho:8000",
            "--workspace-id",
            "gcb-internal",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["summary"]["honcho_messages"] == 1
    assert output["summary"]["unresolved_linear_users"] == 0
    assert output["written_source_refs"] == ["linear:issue:ABC-123"]
    assert "linear:issue:ABC-123" in state_path.read_text(encoding="utf-8")


def test_cli_honcho_sync_write_reports_connection_errors_without_traceback(
    monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "honcho-sync-state.json"

    class FailingHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            pass

        def add_message(self, message):
            raise URLError("connection refused")

    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.HonchoHttpClient", FailingHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--write",
            "--fixture",
            str(FIXTURE),
            "--state",
            str(state_path),
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert str(exc) == "Honcho write failed: <urlopen error connection refused>"
    else:
        raise AssertionError("expected SystemExit")


def test_cli_honcho_sync_live_sources_uses_infisical_snapshot(capsys, monkeypatch) -> None:
    def fake_fetch(config, **kwargs):
        assert config.project_id == "project-123"
        return {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        }

    def fake_collect(secrets, *, limit, catalog_limit, sources, checkpoints, overlap_minutes):
        assert secrets["LINEAR_API_KEY"] == "linear-secret"
        assert limit == 1
        assert catalog_limit == 100
        assert sources == {"linear", "twenty", "slack"}
        assert checkpoints == {}
        assert overlap_minutes == 5
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.fetch_infisical_secrets", fake_fetch)
    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.collect_source_snapshot", fake_collect)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--dry-run",
            "--live-sources",
            "--source-limit",
            "1",
            "--infisical-project-id",
            "project-123",
            "--infisical-env",
            "runtime",
            "--infisical-path",
            "/customer-consumable/customers/4ok/runtime",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["honcho_messages"] == 1
    assert output["messages"][0]["peer"] == "slack_U123456"


def test_cli_honcho_sync_live_sources_uses_runtime_env_defaults(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "honcho-sync-state.json"

    def fake_fetch(config, **kwargs):
        assert config.project_id == "project-from-env"
        assert config.environment == "dev"
        assert config.path == "/customer-consumable/customers/4ok/runtime"
        assert config.domain == "https://infisical.example"
        return {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        }

    def fake_collect(secrets, *, limit, catalog_limit, sources, checkpoints, overlap_minutes):
        assert limit == 1
        assert catalog_limit == 500
        assert sources == {"linear", "slack"}
        assert checkpoints == {}
        assert overlap_minutes == 7
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setenv("INFISICAL_PROJECT_ID", "project-from-env")
    monkeypatch.setenv("INFISICAL_ENV", "dev")
    monkeypatch.setenv("INFISICAL_PATH", "/customer-consumable/customers/4ok/runtime")
    monkeypatch.setenv("INFISICAL_DOMAIN", "https://infisical.example")
    monkeypatch.setenv("HONCHO_SYNC_SOURCES", "linear,slack")
    monkeypatch.setenv("HONCHO_SOURCE_LIMIT", "1")
    monkeypatch.setenv("HONCHO_CATALOG_LIMIT", "500")
    monkeypatch.setenv("HONCHO_CHECKPOINT_OVERLAP_MINUTES", "7")
    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.fetch_infisical_secrets", fake_fetch)
    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.collect_source_snapshot", fake_collect)
    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.HonchoHttpClient", _FakeHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--write",
            "--live-sources",
            "--state",
            str(state_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["written_messages"] == 1


def test_cli_honcho_sync_live_sources_accepts_source_selection(capsys, monkeypatch) -> None:
    def fake_fetch(config, **kwargs):
        return {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        }

    def fake_collect(secrets, *, limit, catalog_limit, sources, checkpoints, overlap_minutes):
        assert sources == {"linear", "slack"}
        assert "TWENTY_API_KEY" in secrets
        assert limit == 1
        assert catalog_limit == 100
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["twenty_workspace_members"] = []
        return data

    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.fetch_infisical_secrets", fake_fetch)
    monkeypatch.setattr("gcb.cli_parts.honcho_helpers.collect_source_snapshot", fake_collect)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "honcho-sync",
            "--dry-run",
            "--summary-only",
            "--live-sources",
            "--sources",
            "linear,slack",
            "--source-limit",
            "1",
            "--infisical-project-id",
            "project-123",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["twenty_workspace_members"] == 0
