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


def test_cli_honcho_sync_dry_run_prints_planned_messages(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "honcho-sync", "--dry-run", "--fixture", str(FIXTURE)],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    expected_text = (
        "Linear issue ABC-123: Olivia Smith created and assigned Olivia Smith a task "
        "titled 'ask Robin to move meeting'. Description: Please ask Robin to move the meeting."
    )
    assert output["mode"] == "dry-run"
    assert output["summary"]["honcho_messages"] == 1
    assert output["messages"] == [
        {
            "peer": "slack_U123456",
            "session": "slack_U123456:linear:2026-06",
            "text": expected_text,
            "metadata": {
                "source": "linear",
                "source_ref": "linear:issue:ABC-123",
                "source_url": "https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
                "source_updated_at": "2026-06-01T10:15:00+00:00",
                "actors": ["employee:email:olivia@example.com"],
                "assignees": ["employee:email:olivia@example.com"],
                "employee_peer": "employee:email:olivia@example.com",
                "honcho_peer_id": "slack_U123456",
                "candidate_entities": ["employee:email:olivia@example.com"],
                "aggregate_fallback_peer": "linear:team:ops",
                "routing_confidence": "high",
                "routing_rule": "linear_assignee_employee_match_v1",
            },
        }
    ]


def test_cli_honcho_sync_summary_only_omits_message_content(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "honcho-sync",
            "--dry-run",
            "--summary-only",
            "--fixture",
            str(FIXTURE),
        ],
    )

    main()

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output == {
        "mode": "dry-run",
        "summary": {
            "twenty_workspace_members": 1,
            "slack_users": 1,
            "linear_users": 1,
            "linear_issues": 1,
            "linear_comments": 0,
            "honcho_messages": 1,
            "unresolved_employee_mappings": 0,
            "unresolved_linear_users": 0,
            "unresolved_slack_users": 0,
        },
    }
    assert "ask Robin" not in output_text


def test_cli_honcho_smoke_skips_when_honcho_is_unavailable(capsys, monkeypatch) -> None:
    def fake_health(self):
        raise URLError("connection refused")

    monkeypatch.setattr("fourok.honcho.client.HonchoHttpClient.health", fake_health)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "honcho-smoke",
            "--honcho-url",
            "http://honcho:8000",
            "--fixture",
            str(FIXTURE),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert output["honcho_url"] == "http://honcho:8000"
    assert "connection refused" in output["reason"]


def test_cli_honcho_smoke_proves_source_ref_readback(capsys, monkeypatch) -> None:
    class FakeHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def health(self):
            return {"status": "ok"}

        def add_message(self, message):
            return [{"id": "msg-1"}]

        def list_messages(self, session_id):
            assert session_id == "slack_U123456:linear:2026-06"
            return {
                "items": [
                    {
                        "id": "msg-1",
                        "metadata": {"source_ref": "linear:issue:ABC-123"},
                    }
                ]
            }

        def search_messages(self, *, query, filters=None, limit=10):
            assert "ABC-123" in query
            assert filters is None
            assert limit == 5
            return [
                {
                    "id": "msg-1",
                    "metadata": {"source_ref": "linear:issue:ABC-123"},
                }
            ]

    monkeypatch.setattr("fourok.cli_parts.honcho_helpers.HonchoHttpClient", FakeHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "honcho-smoke",
            "--honcho-url",
            "http://honcho:8000",
            "--workspace-id",
            "fourok-internal",
            "--fixture",
            str(FIXTURE),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["source_ref_readback"] == {
        "source_ref": "linear:issue:ABC-123",
        "found": True,
    }
    assert output["source_ref_search"] == {
        "source_ref": "linear:issue:ABC-123",
        "found": True,
    }


def test_cli_honcho_eval_scores_expected_source_refs(capsys, monkeypatch, tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(
        json.dumps(
            [
                {
                    "id": "meeting",
                    "query": "ask Robin to move meeting",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                    "expected_entities": ["employee:email:olivia@example.com"],
                    "expected_permission_refs": ["linear:team:sales"],
                },
                {
                    "id": "refund",
                    "query": "refund",
                    "expected_source_refs": ["linear:issue:missing"],
                },
            ]
        ),
        encoding="utf-8",
    )

    class FakeHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def search_messages(self, *, query, filters=None, limit=10):
            assert filters is None
            assert limit == 3
            if "Robin" in query:
                return [
                    {
                        "id": "msg-1",
                        "peer_id": "slack_U123456",
                        "session_id": "slack_U123456_linear_2026-06",
                        "content": "Linear issue ABC-123: Olivia created a task.",
                        "metadata": {
                            "source_ref": "linear:issue:ABC-123",
                            "candidate_entities": ["employee:email:olivia@example.com"],
                            "permission_refs": ["linear:team:sales"],
                        },
                    }
                ]
            return []

    monkeypatch.setattr("fourok.cli_parts.honcho_helpers.HonchoHttpClient", FakeHonchoHttpClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "honcho-eval",
            "--cases",
            str(eval_path),
            "--workspace-id",
            "fourok-internal",
            "--limit",
            "3",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "needs_review"
    assert output["summary"] == {
        "cases": 2,
        "passed": 1,
        "failed": 1,
        "top1_hits": 1,
        "top3_hits": 1,
        "provenance_cases": 1,
    }
    assert output["cases"][0]["found_expected_source_refs"] == ["linear:issue:ABC-123"]
    assert output["cases"][0]["found_expected_entities"] == ["employee:email:olivia@example.com"]
    assert output["cases"][0]["found_expected_permission_refs"] == ["linear:team:sales"]
    assert output["cases"][0]["failure_reason"] is None
    assert output["cases"][0]["top_source_refs"] == ["linear:issue:ABC-123"]
    assert output["cases"][0]["top_content_preview"] == (
        "Linear issue ABC-123: Olivia created a task."
    )
    assert output["cases"][1]["found_expected_source_refs"] == []
    assert output["cases"][1]["failure_reason"] == "missing_expected_source_refs"


def test_cli_honcho_eval_scores_entities_and_permissions_from_dict_items(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(
        json.dumps(
            [
                {
                    "id": "governance",
                    "category": "governance_compatibility",
                    "query": "renewal meeting",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                    "expected_entities": ["employee:email:olivia@example.com"],
                    "expected_permission_refs": ["linear:team:sales", "workflow:renewals"],
                }
            ]
        ),
        encoding="utf-8",
    )

    class FakeHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            pass

        def search_messages(self, *, query, filters=None, limit=10):
            return {
                "items": [
                    {
                        "content": "Olivia created the renewal meeting task.",
                        "metadata": {
                            "source_ref": "linear:issue:ABC-123",
                            "employee_peer": "employee:email:olivia@example.com",
                            "permission_refs": ["linear:team:sales", "workflow:renewals"],
                        },
                    }
                ]
            }

    monkeypatch.setattr("fourok.cli_parts.honcho_helpers.HonchoHttpClient", FakeHonchoHttpClient)
    monkeypatch.setattr("sys.argv", ["fourok", "honcho-eval", "--cases", str(eval_path)])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["passed"] == 1
    assert output["cases"][0]["category"] == "governance_compatibility"
    assert output["cases"][0]["found_expected_entities"] == ["employee:email:olivia@example.com"]
    assert output["cases"][0]["found_expected_permission_refs"] == [
        "linear:team:sales",
        "workflow:renewals",
    ]


def test_cli_evidence_baseline_eval_scores_fixture_source_refs(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(
        json.dumps(
            [
                {
                    "id": "meeting",
                    "query": "ask Robin to move meeting",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "evidence-baseline-eval",
            "--cases",
            str(eval_path),
            "--fixture",
            str(FIXTURE),
            "--limit",
            "3",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["substrate"] == "custom_evidence_baseline"
    assert output["summary"]["passed"] == 1
    assert output["cases"][0]["top_source_refs"] == ["linear:issue:ABC-123"]
    assert output["cases"][0]["top_evidence"][0]["source_url"] == (
        "https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting"
    )


def test_cli_evidence_baseline_eval_runs_context_substrate_cases(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "evidence-baseline-eval",
            "--cases",
            str(CONTEXT_SUBSTRATE_CASES),
            "--fixture",
            str(CONTEXT_SUBSTRATE_FIXTURE),
            "--limit",
            "5",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["summary"] == {
        "cases": 15,
        "passed": 15,
        "failed": 0,
        "top1_hits": 12,
        "top3_hits": 15,
        "provenance_cases": 15,
    }
    assert {case["category"] for case in output["cases"]} == {
        "chat_acquired_knowledge",
        "day2_lifecycle",
        "entity_linking_ambiguous",
        "entity_linking_exact",
        "governance_compatibility",
        "retrieval_provenance",
    }
    assert all("failure_reason" in case for case in output["cases"])


def test_cli_graphiti_episodes_dry_run_prints_episode_contract(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "graphiti-episodes",
            "--fixture",
            str(FIXTURE),
            "--group-id",
            "fourok-fixture",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["substrate"] == "graphiti"
    assert output["summary"] == {
        "episodes": 6,
        "message_episodes": 1,
        "json_episodes": 5,
    }
    assert output["episodes"][0]["uuid"] == "fourok:graphiti:linear:issue:ABC-123"
    assert output["episodes"][0]["metadata"]["source_ref"] == "linear:issue:ABC-123"


def test_cli_honcho_eval_can_scope_to_peer_search(capsys, monkeypatch, tmp_path: Path) -> None:
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(
        json.dumps(
            [
                {
                    "id": "meeting",
                    "query": "meeting",
                    "peer_id": "slack_U123456",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                }
            ]
        ),
        encoding="utf-8",
    )

    class FakeHonchoHttpClient:
        def __init__(self, **kwargs) -> None:
            pass

        def search_peer(self, *, peer_id, query, filters=None, limit=10):
            assert peer_id == "slack_U123456"
            return [{"metadata": {"source_ref": "linear:issue:ABC-123"}}]

    monkeypatch.setattr("fourok.cli_parts.honcho_helpers.HonchoHttpClient", FakeHonchoHttpClient)
    monkeypatch.setattr("sys.argv", ["fourok", "honcho-eval", "--cases", str(eval_path)])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["passed"] == 1










def test_cli_honcho_sync_dry_run_classifies_already_imported_source_refs(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state_path.write_text(
        (
            '{"source_refs":{"linear:issue:ABC-123":'
            '{"honcho_message_id":"msg-123","honcho_peer_id":"slack_U123456",'
            '"rule_version":"linear_assignee_employee_match_v1"}},'
            '"checkpoints":{}}'
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
            str(FIXTURE),
            "--state",
            str(state_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["idempotency"] == {
        "new_source_refs": [],
        "changed_source_refs": [],
        "skipped_source_refs": ["linear:issue:ABC-123"],
    }


def test_cli_honcho_sync_dry_run_reports_changed_source_refs(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    fixture_path = tmp_path / "changed-linear.json"
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"][0]["updated_at"] = "2026-06-01T10:25:00+00:00"
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    state_path = tmp_path / "honcho-sync-state.json"
    state_path.write_text(
        (
            '{"source_refs":{"linear:issue:ABC-123":'
            '{"honcho_message_id":"msg-123","honcho_peer_id":"slack_U123456",'
            '"rule_version":"linear_assignee_employee_match_v1",'
            '"source_updated_at":"2026-06-01T10:15:00+00:00"}},'
            '"checkpoints":{}}'
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
    assert output["idempotency"] == {
        "new_source_refs": [],
        "changed_source_refs": ["linear:issue:ABC-123"],
        "skipped_source_refs": [],
    }


def test_cli_honcho_receipt_prints_stored_source_receipt(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "honcho-sync-state.json"
    state_path.write_text(
        json.dumps(
            {
                "source_refs": {
                    "linear:issue:ABC-123": {
                        "honcho_message_id": "msg-123",
                        "honcho_peer_id": "slack_U123456",
                        "honcho_session_id": "slack_U123456:linear:2026-06",
                        "rule_version": "linear_assignee_employee_match_v1",
                        "routing_confidence": "high",
                        "employee_peer": "employee:email:olivia@example.com",
                        "candidate_entities": "employee:email:olivia@example.com",
                        "aggregate_fallback_peer": "linear:team:ops",
                        "source_url": "https://linear.app/acme/issue/ABC-123",
                        "source_updated_at": "2026-06-01T10:15:00+00:00",
                        "written_at": "2026-06-01T10:20:00+00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "honcho-receipt",
            "linear:issue:ABC-123",
            "--state",
            str(state_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "source_ref": "linear:issue:ABC-123",
        "receipt": {
            "honcho_message_id": "msg-123",
            "honcho_peer_id": "slack_U123456",
            "honcho_session_id": "slack_U123456:linear:2026-06",
            "rule_version": "linear_assignee_employee_match_v1",
            "routing_confidence": "high",
            "employee_peer": "employee:email:olivia@example.com",
            "candidate_entities": "employee:email:olivia@example.com",
            "aggregate_fallback_peer": "linear:team:ops",
            "source_url": "https://linear.app/acme/issue/ABC-123",
            "source_updated_at": "2026-06-01T10:15:00+00:00",
            "written_at": "2026-06-01T10:20:00+00:00",
        },
    }
