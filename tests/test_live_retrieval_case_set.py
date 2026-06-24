import json
from pathlib import Path

import pytest

from fourok.cli import main
from fourok.etl.extract.connectors import (
    load_google_drive_source_records,
    load_linear_source_records,
    load_slack_source_records,
    load_twenty_source_records,
)
from fourok.etl.extract.openviking_adapter import (
    load_openviking_messages_jsonl_source_records,
)
from fourok.governance import GovernedContext
from fourok.retrieval.live_retrieval_case_set import (
    DEFAULT_GOOGLE_DRIVE_FIXTURE,
    DEFAULT_LINEAR_FIXTURE,
    DEFAULT_OPENVIKING_FIXTURE,
    DEFAULT_SLACK_FIXTURE,
    DEFAULT_TWENTY_FIXTURE,
)

REPO_ROOT = Path(__file__).parent.parent
CASES = REPO_ROOT / "fixtures" / "retrieval_eval" / "live_retrieval_case_set.json"
SEEDED_CASES = REPO_ROOT / "fixtures" / "retrieval_eval" / "seeded_retrieval_case_set.json"
SLACK_FIXTURE = REPO_ROOT / DEFAULT_SLACK_FIXTURE
DRIVE_FIXTURE = REPO_ROOT / DEFAULT_GOOGLE_DRIVE_FIXTURE
OPENVIKING_FIXTURE = REPO_ROOT / DEFAULT_OPENVIKING_FIXTURE
LINEAR_FIXTURE = REPO_ROOT / DEFAULT_LINEAR_FIXTURE
TWENTY_FIXTURE = REPO_ROOT / DEFAULT_TWENTY_FIXTURE


def test_live_retrieval_case_set_fails_with_missing_expected_source_ref(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    broken_cases = tmp_path / "cases-bad.json"
    broken_cases.write_text(
        json.dumps(
            [
                {
                    "id": "broken",
                    "query": "does-not-matter",
                    "expected_source_ref_prefix": "slack:message:missing",
                    "expected_source_system": "slack",
                    "expected_record_type": "message",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    state = tmp_path / "state.sqlite"
    report_path = tmp_path / "report.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "live-retrieval-case-set",
            "--cases",
            str(broken_cases),
            "--seed-fixtures",
            "--state",
            str(state),
            "--report",
            str(report_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "needs_review"
    assert output["summary"]["failed"] == 1
    assert output["cases"][0]["failure_reason"] == "expected_source_ref_not_found_in_results"
    assert report_path.exists()


def test_live_retrieval_case_set_passes_with_seeded_fixtures(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.sqlite"
    report_path = tmp_path / "report.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "live-retrieval-case-set",
            "--state",
            str(state),
            "--cases",
            str(SEEDED_CASES),
            "--seed-fixtures",
            "--report",
            str(report_path),
        ],
    )

    main()
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "ok"
    assert output["summary"] == {
        "cases": 5,
        "passed": 5,
        "failed": 0,
    }
    case_ids = [item["id"] for item in output["cases"]]
    assert case_ids == [
        "slack-cancellation-invoice",
        "google-drive-metadata-only",
        "openviking-launch-checklist",
        "linear-issue-cancellation-summary",
        "twenty-company-alpha",
    ]
    assert all(item["passed"] for item in output["cases"])
    assert output["seed_report"]["record_count"] == 11
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "# Live Retrieval Case Set Check Report" in report_text
    assert "status: ok" in report_text


def test_live_retrieval_case_set_uses_runtime_database_when_configured(
    capsys,
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_case = tmp_path / "cases-single.json"
    runtime_case.write_text(
        json.dumps(
            [
                {
                    "id": "openviking-runtime",
                    "query": "Alpine Robotics launch checklist",
                    "expected_source_ref_prefix": (
                        "openviking:conversation:conv-product:session:sess-alpha:message:m-001"
                    ),
                    "expected_source_system": "openviking",
                    "expected_record_type": "message",
                    "expected_permission_refs": ["openviking:conversation:conv-product"],
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    database_path = tmp_path / "runtime.sqlite"
    database_url = f"sqlite:///{database_path}"
    context = GovernedContext(database_url=database_url)
    context.ingest_source_records(
        load_openviking_messages_jsonl_source_records(OPENVIKING_FIXTURE)
        + load_slack_source_records(SLACK_FIXTURE)
        + load_google_drive_source_records(DRIVE_FIXTURE)
        + load_linear_source_records(LINEAR_FIXTURE)
        + load_twenty_source_records(TWENTY_FIXTURE)
    )

    monkeypatch.setenv("FOUROK_DATABASE_URL", database_url)
    report_path = tmp_path / "report-runtime.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "live-retrieval-case-set",
            "--cases",
            str(runtime_case),
            "--report",
            str(report_path),
        ],
    )

    main()
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "ok"
    assert output["cases"][0]["passed"] is True
    assert output["cases"][0]["failure_reason"] is None
    assert report_path.exists()
