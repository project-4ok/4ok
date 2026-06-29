import json
import subprocess
import sys
from pathlib import Path

from fourok.cli import main
from fourok.etl.extract.connectors import load_singer_source_records
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext

FIXTURES = Path(__file__).parent / "fixtures" / "emails"
CONNECTOR_FIXTURES = Path(__file__).parent / "fixtures" / "connectors"
CONTEXT_FIXTURES = Path(__file__).parent / "fixtures" / "context_substrate"


def _source_record_legacy_fields(row: dict[str, object]) -> dict[str, object]:
    keys = [
        "source_ref",
        "source_system",
        "source_id",
        "record_type",
        "source_url",
        "thread_ref",
        "permission_refs",
        "permission_snapshot_status",
        "attachment_refs",
        "identity_refs",
        "lifecycle_state",
    ]
    return {key: row[key] for key in keys}


def test_cli_search_prints_json_results(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search",
            "refund cancellation payment",
            "--emails",
            str(FIXTURES),
            "--state",
            str(state),
            "--limit",
            "2",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["query"] == "refund cancellation payment"
    assert len(output["results"]) == 2
    assert {
        "source_ref",
        "subject",
        "date",
        "snippet",
    } <= output["results"][0].keys()
    assert output["load"] == {"loaded": 14, "skipped": 0, "skipped_files": []}


def test_cli_governed_search_and_audit_exposes_no_reveal_tokens(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search",
            "refund iban canceled account",
            "--emails",
            str(FIXTURES),
            "--state",
            str(state),
            "--limit",
            "3",
        ],
    )
    main()
    search_output = json.loads(capsys.readouterr().out)

    assert "sensitive_tokens" not in search_output
    assert "BANK_ACCOUNT_" not in str(search_output)

    monkeypatch.setattr("sys.argv", ["fourok", "audit", "--state", str(state)])
    main()
    audit_output = json.loads(capsys.readouterr().out)
    assert [event["event_type"] for event in audit_output["events"]] == [
        "search",
        "source_access",
    ]


def test_cli_search_state_explicit_sqlite_state_ignores_ambient_database_url(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    class FakeSearchResponse:
        results: list[object] = []
        summary: dict[str, object] = {}
        result_candidates: list[object] = []
        evidence_items: list[object] = []
        primary_objects: list[object] = []
        related_objects: list[object] = []
        related_object_groups: list[object] = []
        entities: list[object] = []
        unresolved_candidates: list[object] = []
        limitations: list[object] = []
        audit_ref = "audit:test"

    class FakeContext:
        def __init__(self, state_path: Path, *, database_url: str | None = None):
            calls.append({"state_path": state_path, "database_url": database_url})

        def search_context(self, *_args, **_kwargs):
            return FakeSearchResponse()

    state = tmp_path / "state.sqlite"
    monkeypatch.setenv(
        "FOUROK_DATABASE_URL",
        "postgresql+psycopg://fourok:stale@127.0.0.1:5432/fourok",
    )
    monkeypatch.setattr("fourok.retrieval.cli.GovernedContext", FakeContext)
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "search-state", "refund", "--state", str(state)],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["query"] == "refund"
    assert output["results"] == []
    assert output["load"] == {"loaded": 0, "source": "existing_state"}
    assert calls == [{"state_path": state, "database_url": None}]


def test_cli_reveal_command_is_not_active(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "reveal", "BANK_ACCOUNT_OLD"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("inactive reveal command should fail argument parsing")


def test_cli_graphiti_episodes_command_is_not_registered(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "graphiti-episodes",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("retired graphiti command should fail argument parsing")


def test_cli_help_hides_research_experiment_commands(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "--help"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("argparse help should exit")

    output = capsys.readouterr().out
    assert "retrieve" in output
    assert "status" in output
    assert "onboard" in output
    assert "admin" in output
    assert "eval-retrieval" not in output
    assert "\n  source " not in output
    assert "honcho-sync" not in output
    assert "honcho-receipt" not in output
    assert "honcho-smoke" not in output
    assert "honcho-eval" not in output
    assert "honcho-preflight" not in output
    assert "graphiti-episodes" not in output
    assert "evidence-baseline-eval" not in output


def test_fixture_cli_help_marks_fixture_paths_as_test_only(capsys, monkeypatch) -> None:
    for argv, expected in [
        (
            ["fourok", "import-context-fixture", "--help"],
            "test-only deterministic context snapshot",
        ),
        (
            ["fourok", "run-imports", "--help"],
            "context-fixture is regression-only",
        ),
        (
            ["fourok", "acceptance-proof", "--help"],
            "Fixture seed for deterministic regression proof only",
        ),
        (
            ["fourok", "search", "--help"],
            "Search local email fixture regression data",
        ),
    ]:
        monkeypatch.setattr("sys.argv", argv)
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("argparse help should exit")

        assert expected in capsys.readouterr().out


def test_cli_import_does_not_load_hidden_experiment_modules() -> None:
    script = (
        "import sys; import fourok.cli; "
        "print(any(name.startswith('fourok.honcho') "
        "for name in sys.modules))"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_cli_goal_audit_reports_alignment(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "goal-audit"])

    main()
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "ok"
    assert output["summary"]["failed"] == 0
    check_names = {check["name"] for check in output["checks"]}
    assert "plan_active_queue" in check_names
    assert "goal_backlog_has_open_items_for_active_plan" in check_names


def test_cli_access_smoke_prints_compose_access_report(capsys, monkeypatch, tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    def fake_check(*, compose_file: Path) -> dict[str, object]:
        return {
            "status": "ok",
            "compose_file": str(compose_file),
            "exposures": [],
            "violations": [],
            "skipped_services": [],
        }

    monkeypatch.setattr("fourok.runtime.cli.check_compose_access_boundary", fake_check)
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "access-smoke", "--compose-file", str(compose_file)],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "ok",
        "compose_file": str(compose_file),
        "exposures": [],
        "violations": [],
        "skipped_services": [],
    }


def test_cli_eval_retrieval_runs_default_golden_query_fixture(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "eval-retrieval"])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["substrate"] == "governed_context"
    assert output["status"] == "ok"
    assert output["summary"] == {
        "cases": 5,
        "passed": 5,
        "failed": 0,
        "top1_hits": 5,
        "top3_hits": 5,
        "evidence_pack_cases": 5,
        "audit_cases": 5,
        "unacceptable_source_checks": 1,
        "unacceptable_source_violations": 0,
    }
    assert output["cases"][0]["audit_ref"].startswith("audit:search:")
    assert output["cases"][0]["evidence_item_count"] >= 1
    lifecycle_case = next(
        case for case in output["cases"] if case["id"] == "lifecycle_filters_superseded"
    )
    assert lifecycle_case["unacceptable_source_refs"] == ["linear:issue:duplicate"]
    assert lifecycle_case["found_unacceptable_source_refs"] == []


def test_cli_lands_singer_records(capsys, monkeypatch, tmp_path: Path) -> None:
    landing_dir = tmp_path / "raw"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "land-singer",
            str(CONNECTOR_FIXTURES / "singer_email_messages.jsonl"),
            "--landing-dir",
            str(landing_dir),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "landing_dir": str(landing_dir),
        "record_count": 2,
        "streams": {"email_messages": 2},
        "schema_messages": 1,
        "state_messages": 1,
    }
    assert (landing_dir / "email_messages.jsonl").exists()


def test_cli_ingests_gmail_singer_records_into_state(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    singer_file = tmp_path / "gmail-output.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"messages","record":'
            "{"
            '"id":"gmail-msg-6",'
            '"threadId":"thread-6",'
            '"internalDate":"1716998096000",'
            '"userId":"me",'
            '"snippet":"fallback snippet",'
            '"payload":{'
            '"headers":['
            '{"name":"Subject","value":"Pilot subject"},'
            '{"name":"From","value":"Sender Name <sender@example.com>"},'
            '{"name":"To","value":"ops@example.com"}'
            "],"
            '"parts":[{"mimeType":"text/plain","body":{"data":"UGlsb3QgYm9keSB0ZXh0"}}]'
            "}"
            "}}\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "ingest-gmail-singer",
            str(singer_file),
            "--state",
            str(state),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    context = GovernedContext(state)
    assert output == {
        "input": str(singer_file),
        "record_count": 1,
        "source_refs": ["gmail:message:gmail-msg-6"],
        "restricted_count": 1,
    }
    stored = context.source_records()
    assert [_source_record_legacy_fields(row) for row in stored] == [
        {
            "source_ref": "gmail:message:gmail-msg-6",
            "source_system": "gmail",
            "source_id": "gmail-msg-6",
            "record_type": "email",
            "source_url": "https://mail.google.com/mail/u/me/#all/thread-6/gmail-msg-6",
            "thread_ref": "gmail:thread:thread-6",
            "permission_refs": "[]",
            "permission_snapshot_status": "missing",
            "attachment_refs": "[]",
            "identity_refs": '["gmail:email:sender@example.com", "gmail:email:ops@example.com"]',
            "lifecycle_state": "restricted",
        }
    ]
    assert stored[0]["title"] == "Pilot subject"
    assert stored[0]["retrieval_text"] == "Pilot body text"
    assert stored[0]["occurred_at"] == "2024-05-29T15:54:56+00:00"


def test_cli_ingests_flat_gmail_singer_records_with_current_permissions(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    singer_file = tmp_path / "gmail-flat-output.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"messages","record":'
            '{"id":"gmail-msg-7","subject":"Finance note","body":"flat gmail body marker",'
            '"permission_refs":["group:finance"],'
            '"permission_snapshot_status":"current"}}\n'
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "ingest-gmail-singer",
            str(singer_file),
            "--state",
            str(state),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    context = GovernedContext(state)
    assert output == {
        "input": str(singer_file),
        "record_count": 1,
        "source_refs": ["gmail:messages:gmail-msg-7"],
        "restricted_count": 0,
    }
    stored = context.source_records()
    assert [_source_record_legacy_fields(row) for row in stored] == [
        {
            "source_ref": "gmail:messages:gmail-msg-7",
            "source_system": "gmail",
            "source_id": "gmail-msg-7",
            "record_type": "email",
            "source_url": "https://mail.google.com/mail/u/0/#all/gmail-msg-7",
            "thread_ref": "",
            "permission_refs": '["group:finance"]',
            "permission_snapshot_status": "current",
            "attachment_refs": "[]",
            "identity_refs": "[]",
            "lifecycle_state": "active",
        }
    ]
    assert stored[0]["title"] == "Finance note"
    assert stored[0]["retrieval_text"] == "flat gmail body marker"
    assert [
        result.source_ref
        for result in context.search_context(
            "body marker",
            principal=PrincipalContext(
                human_id="human:finance-1",
                agent_id="agent:context-helper",
                roles=("finance",),
            ),
        ).results
    ] == ["gmail:messages:gmail-msg-7"]


def test_cli_search_state_queries_existing_governed_state_without_loading_fixtures(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        load_singer_source_records(CONNECTOR_FIXTURES / "singer_email_messages.jsonl")
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search-state",
            "finance secret iban",
            "--state",
            str(state),
            "--human-id",
            "human:finance-1",
            "--agent-id",
            "agent:context-helper",
            "--role",
            "finance",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["query"] == "finance secret iban"
    assert output["load"] == {"loaded": 0, "source": "existing_state"}
    assert [result["source_ref"] for result in output["results"]] == [
        "singer:email_messages:msg-001"
    ]
    assert "DE89370400440532013000" in str(output)
    assert "sensitive_tokens" not in output


def test_cli_imports_context_fixture_and_searches_source_records(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "import-context-fixture",
            "--fixture",
            str(fixture),
            "--state",
            str(state),
        ],
    )
    main()
    import_output = json.loads(capsys.readouterr().out)

    assert import_output["input"] == str(fixture)
    assert import_output["record_count"] == 20
    assert "linear:issue:ABC-123" in import_output["source_refs"]
    assert import_output["canonical_object_count"] == 20
    assert import_output["entity_link_count"] >= 6

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search-state",
            "renewal meeting Thursday",
            "--state",
            str(state),
            "--human-id",
            "human:sales-1",
            "--agent-id",
            "agent:context-helper",
            "--role",
            "linear:team:sales",
        ],
    )
    main()
    search_output = json.loads(capsys.readouterr().out)

    assert search_output["query"] == "renewal meeting Thursday"
    assert search_output["result_candidates"][0]["ranking_reason"] == (
        "keyword match in permission-filtered retrieval unit"
    )
    assert search_output["result_candidates"][0]["source_ref"] in {
        "linear:comment:linear-comment-1",
        "linear:comment:linear-comment-3",
        "linear:issue:ABC-123",
    }
    assert search_output["evidence_items"][0]["source_ref"] in {
        "linear:comment:linear-comment-1",
        "linear:comment:linear-comment-3",
        "linear:issue:ABC-123",
    }
    assert search_output["evidence_items"][0]["source_type"] in {"Message", "WorkItem"}
    assert search_output["evidence_items"][0]["source_system"] == "linear"
    assert search_output["evidence_items"][0]["why_included"] == (
        "matched permission-filtered retrieval text"
    )
    olivia_entity = next(
        entity
        for entity in search_output["entities"]
        if entity["entity_ref"] == "employee:email:olivia@example.com"
    )
    assert olivia_entity["object_ref"] == "linear:user:linear-user-olivia"
    assert olivia_entity["display_name"] == "Olivia Smith"
    assert "linear:issue:ABC-123" in olivia_entity["source_refs"]
    assert olivia_entity["relationship_types"] == ["assignee", "author"]
    assert olivia_entity["confidence"] == 1.0
    assert olivia_entity["reason"] == "deterministic_source_identity"
    assert olivia_entity["status"] == "linked"
    assert (
        "employee:email:olivia@example.com" in search_output["evidence_items"][0]["linked_entities"]
    )
    assert search_output["primary_objects"][0]["object_type"] in {"Message", "WorkItem"}
    assert search_output["audit_ref"].startswith("audit:search:")


def test_cli_prepare_seed_snapshot_writes_local_seed_manifest(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"
    output = tmp_path / ".local" / "seeds" / "context-substrate.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "prepare-seed-snapshot",
            "--input",
            str(fixture),
            "--output",
            str(output),
        ],
    )

    main()

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["output"] == str(output)
    assert report["manifest"] == str(output.with_suffix(".manifest.json"))
    assert report["record_count"] == 20
    assert report["source_system_counts"] == {"linear": 14, "slack": 3, "twenty": 3}
    assert "Robin Scharf confirmed" not in str(report)
    assert output.exists()
    assert output.with_suffix(".manifest.json").exists()


def test_cli_search_state_returns_source_backed_related_objects(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"
    context = GovernedContext(state)
    from fourok.etl.extract.context_snapshot import load_context_snapshot_source_records

    context.ingest_source_records(load_context_snapshot_source_records(fixture))

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search-state",
            "ask Robin Scharf renewal meeting",
            "--state",
            str(state),
            "--human-id",
            "human:sales-1",
            "--agent-id",
            "agent:context-helper",
            "--role",
            "linear:team:sales",
            "--limit",
            "1",
        ],
    )
    main()
    output = json.loads(capsys.readouterr().out)

    assert output["results"][0]["source_ref"] == "linear:issue:ABC-123"
    assert output["related_objects"] == [
        {
            "object_ref": "linear:user:linear-user-olivia",
            "object_type": "Person",
            "title": "Olivia Smith",
            "relationship_to_primary": "linked entity: assignee, author",
            "relationship_source_refs": ["linear:issue:ABC-123"],
            "confidence": 1.0,
            "follow_up_hint": "Ask about Olivia Smith",
        },
        {
            "object_ref": "linear:project:project-meetings",
            "object_type": "WorkItem",
            "title": "Meeting Operations",
            "relationship_to_primary": "same project",
            "relationship_source_refs": [
                "linear:issue:ABC-123",
                "linear:project:project-meetings",
            ],
            "confidence": 0.85,
            "follow_up_hint": "Ask about Meeting Operations",
        },
        {
            "object_ref": "linear:comment:linear-comment-1",
            "object_type": "Message",
            "title": "Comment on ABC-123",
            "relationship_to_primary": "same thread",
            "relationship_source_refs": [
                "linear:issue:ABC-123",
                "linear:comment:linear-comment-1",
            ],
            "confidence": 0.9,
            "follow_up_hint": "Ask about Comment on ABC-123",
        },
        {
            "object_ref": "linear:comment:linear-comment-3",
            "object_type": "Message",
            "title": "Comment on ABC-123",
            "relationship_to_primary": "same thread",
            "relationship_source_refs": [
                "linear:issue:ABC-123",
                "linear:comment:linear-comment-3",
            ],
            "confidence": 0.9,
            "follow_up_hint": "Ask about Comment on ABC-123",
        },
    ]
    assert output["related_object_groups"] == {
        "people": [
            {
                "object_ref": "linear:user:linear-user-olivia",
                "object_type": "Person",
                "title": "Olivia Smith",
                "relationship_to_primary": "linked entity: assignee, author",
                "relationship_source_refs": ["linear:issue:ABC-123"],
                "confidence": 1.0,
                "follow_up_hint": "Ask about Olivia Smith",
            }
        ],
        "organizations": [],
        "work_items": [
            {
                "object_ref": "linear:project:project-meetings",
                "object_type": "WorkItem",
                "title": "Meeting Operations",
                "relationship_to_primary": "same project",
                "relationship_source_refs": [
                    "linear:issue:ABC-123",
                    "linear:project:project-meetings",
                ],
                "confidence": 0.85,
                "follow_up_hint": "Ask about Meeting Operations",
            }
        ],
        "documents": [],
        "threads": [
            {
                "object_ref": "linear:comment:linear-comment-1",
                "object_type": "Message",
                "title": "Comment on ABC-123",
                "relationship_to_primary": "same thread",
                "relationship_source_refs": [
                    "linear:issue:ABC-123",
                    "linear:comment:linear-comment-1",
                ],
                "confidence": 0.9,
                "follow_up_hint": "Ask about Comment on ABC-123",
            },
            {
                "object_ref": "linear:comment:linear-comment-3",
                "object_type": "Message",
                "title": "Comment on ABC-123",
                "relationship_to_primary": "same thread",
                "relationship_source_refs": [
                    "linear:issue:ABC-123",
                    "linear:comment:linear-comment-3",
                ],
                "confidence": 0.9,
                "follow_up_hint": "Ask about Comment on ABC-123",
            },
        ],
    }
    assert output["unresolved_candidates"] == []


def test_cli_search_state_returns_ambiguous_person_candidates(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"
    context = GovernedContext(state)
    from fourok.etl.extract.context_snapshot import load_context_snapshot_source_records

    context.ingest_source_records(load_context_snapshot_source_records(fixture))

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search-state",
            "Robin renewal meeting Thursday",
            "--state",
            str(state),
            "--human-id",
            "human:sales-1",
            "--agent-id",
            "agent:context-helper",
            "--role",
            "linear:team:sales",
            "--limit",
            "2",
        ],
    )
    main()
    output = json.loads(capsys.readouterr().out)

    assert output["unresolved_candidates"] == [
        {
            "candidate_ref": "candidate:person:robin:linear:user:linear-user-robin-keller",
            "object_ref": "linear:user:linear-user-robin-keller",
            "object_type": "Person",
            "display_name": "Robin Keller",
            "matched_text": "robin",
            "confidence": 0.5,
            "reason": "ambiguous_visible_person_name",
            "status": "unresolved",
        },
        {
            "candidate_ref": "candidate:person:robin:linear:user:linear-user-robin-scharf",
            "object_ref": "linear:user:linear-user-robin-scharf",
            "object_type": "Person",
            "display_name": "Robin Scharf",
            "matched_text": "robin",
            "confidence": 0.5,
            "reason": "ambiguous_visible_person_name",
            "status": "unresolved",
        },
    ]
