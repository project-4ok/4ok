import importlib.util
from pathlib import Path

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext

_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_slack_live_contract.py"
_SPEC = importlib.util.spec_from_file_location("check_slack_live_contract", _SCRIPT)
assert _SPEC is not None
slack_live_contract = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(slack_live_contract)


def test_slack_env_defaults_to_all_readable_channel_types(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TAP_SLACK_CHANNEL_TYPES", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

    env = slack_live_contract._slack_env()

    assert env["TAP_SLACK_CHANNEL_TYPES"] == '["public_channel","private_channel","mpim","im"]'
    assert env["TAP_SLACK_INCLUDE_ADMIN_STREAMS"] == "false"
    assert "TAP_SLACK_SELECTED_CHANNELS" not in env


def test_slack_env_uses_exported_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

    env = slack_live_contract._slack_env()

    assert env["TAP_SLACK_API_KEY"] == "xoxb-test"


def test_slack_env_removes_explicit_channel_type_limits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TAP_SLACK_CHANNEL_TYPES", '["private_channel"]')
    monkeypatch.setenv("TAP_SLACK_SELECTED_CHANNELS", '["CEXPLICIT"]')
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

    env = slack_live_contract._slack_env()

    assert env["TAP_SLACK_CHANNEL_TYPES"] == '["public_channel","private_channel","mpim","im"]'
    assert "TAP_SLACK_SELECTED_CHANNELS" not in env


def test_live_checker_reports_missing_credentials_as_blocker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TAP_SLACK_API_KEY", raising=False)

    report = slack_live_contract.check_slack_live_contract(tmp_path / "artifacts")

    assert report["status"] == "blocked"
    assert report["stage"] == "credentials"
    assert report["credential_inputs"] == {
        "has_slack_token": False,
        "has_dotenv": False,
    }
    assert report["runtime_database"] == {
        "status": "skipped",
        "reason": "database_url_not_set",
    }


def test_runtime_probe_and_mcp_gate_prove_slack_permission_filtering(tmp_path: Path) -> None:
    database_path = tmp_path / "fourok.sqlite"
    database_url = f"sqlite:///{database_path}"
    context = GovernedContext(tmp_path / "unused.sqlite", database_url=database_url)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:C1:1717236300.000000",
                source_system="slack",
                source_id="C1:1717236300.000000",
                record_type="message",
                title="#ops",
                body="mcppermissionmarker escalation update",
                permission_refs=("slack:channel:C1",),
            )
        ]
    )

    runtime_database = slack_live_contract._runtime_database_probe(database_url)
    mcp_gate = slack_live_contract._mcp_permission_gate_probe(database_url, runtime_database)
    slack_live_contract._drop_private_probe_fields(runtime_database)

    assert runtime_database == {
        "status": "ok",
        "active_slack_message_source_records": 1,
        "current_slack_message_retrieval_records": 1,
        "mcp_candidate": {
            "source_ref": "slack:message:C1:1717236300.000000",
            "permission_refs": ["slack:channel:C1"],
        },
    }
    assert mcp_gate == {
        "status": "ok",
        "candidate_source_ref": "slack:message:C1:1717236300.000000",
        "candidate_permission_refs": ["slack:channel:C1"],
        "allowed_result_count": 1,
        "allowed_evidence_count": 1,
        "allowed_includes_candidate": True,
        "allowed_evidence_includes_candidate": True,
        "denied_result_count": 0,
        "denied_evidence_count": 0,
    }
