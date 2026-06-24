import json
from pathlib import Path
from urllib.error import URLError

from fourok.cli import main

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
            "fourok",
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
            "fourok",
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


def test_cli_honcho_sync_write_persists_receipts(capsys, monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "honcho-sync-state.json"

    class FakeHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def add_message(self, message):
            return [{"id": "msg-1"}]

    monkeypatch.setattr("fourok.cli_parts.honcho_helpers.HonchoHttpClient", FakeHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "honcho-sync",
            "--write",
            "--fixture",
            str(FIXTURE),
            "--state",
            str(state_path),
            "--honcho-url",
            "http://honcho:8000",
            "--workspace-id",
            "fourok-internal",
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

    monkeypatch.setattr("fourok.cli_parts.honcho_helpers.HonchoHttpClient", FailingHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
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
