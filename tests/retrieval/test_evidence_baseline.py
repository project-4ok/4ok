import json
from pathlib import Path

from fourok.retrieval.evidence_baseline import evaluate_evidence_baseline, search_evidence

FIXTURE = (
    Path(__file__).parent.parent.parent / "fixtures" / "honcho" / "linear_twenty_slack_sample.json"
)


def test_search_evidence_returns_ranked_evidence_pack_with_provenance() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    pack = search_evidence(data, "ask Robin to move meeting", limit=3)

    assert pack["query"] == "ask Robin to move meeting"
    assert pack["summary"] == (
        "Top evidence: linear:issue:ABC-123 from linear. 1 of 6 indexed records matched."
    )
    assert pack["evidence"][0] == {
        "source_ref": "linear:issue:ABC-123",
        "source": "linear",
        "source_type": "message",
        "score": 5,
        "title": "linear:issue:ABC-123",
        "snippet": (
            "Linear issue ABC-123: Olivia Smith created and assigned Olivia Smith a task "
            "titled 'ask Robin to move meeting'. Description: Please ask Robin to move the meeting."
        ),
        "source_url": "https://linear.app/acme/issue/ABC-123/ask-robin-to-move-meeting",
        "source_updated_at": "2026-06-01T10:15:00+00:00",
        "entities": ["employee:email:olivia@example.com"],
        "permission_refs": [],
        "metadata": {
            "actors": ["employee:email:olivia@example.com"],
            "aggregate_fallback_peer": "linear:team:ops",
            "assignees": ["employee:email:olivia@example.com"],
            "candidate_entities": ["employee:email:olivia@example.com"],
            "employee_peer": "employee:email:olivia@example.com",
            "honcho_peer_id": "slack_U123456",
            "routing_confidence": "high",
            "routing_rule": "linear_assignee_employee_match_v1",
        },
    }


def test_search_evidence_returns_permission_refs_when_sources_provide_them() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["linear_issues"][0]["permission_refs"] = ["linear:team:ops", "workflow:renewals"]

    pack = search_evidence(data, "ask Robin to move meeting", limit=3)

    assert pack["evidence"][0]["permission_refs"] == ["linear:team:ops", "workflow:renewals"]
    assert pack["evidence"][0]["metadata"]["permission_refs"] == [
        "linear:team:ops",
        "workflow:renewals",
    ]


def test_search_evidence_includes_identity_catalog_records() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    pack = search_evidence(data, "Olivia Slack Linear Twenty employee", limit=5)

    assert [item["source_ref"] for item in pack["evidence"][:3]] == [
        "linear:user:linear-user-olivia",
        "slack:user:U123456",
        "twenty:workspaceMember:twenty-member-olivia",
    ]
    assert all(
        item["entities"] == ["employee:email:olivia@example.com"] for item in pack["evidence"][:3]
    )


def test_evaluate_evidence_baseline_scores_expected_source_refs() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = [
        {
            "id": "linear_issue",
            "query": "ask Robin to move meeting",
            "expected_source_refs": ["linear:issue:ABC-123"],
            "expected_entities": ["employee:email:olivia@example.com"],
            "expected_permission_refs": ["linear:team:ops"],
        },
        {
            "id": "missing",
            "query": "bank refund",
            "expected_source_refs": ["linear:issue:missing"],
            "expected_entities": ["employee:email:missing@example.com"],
        },
    ]

    report = evaluate_evidence_baseline(data, cases, limit=3)

    assert report["status"] == "needs_review"
    assert report["summary"] == {
        "cases": 2,
        "passed": 0,
        "failed": 2,
        "top1_hits": 1,
        "top3_hits": 1,
        "provenance_cases": 1,
    }
    assert report["cases"][0]["found_expected_source_refs"] == ["linear:issue:ABC-123"]
    assert report["cases"][0]["expected_entities"] == ["employee:email:olivia@example.com"]
    assert report["cases"][0]["found_expected_entities"] == ["employee:email:olivia@example.com"]
    assert report["cases"][0]["expected_permission_refs"] == ["linear:team:ops"]
    assert report["cases"][0]["found_expected_permission_refs"] == []
    assert report["cases"][0]["failure_reason"] == "missing_expected_permission_refs"
    assert not report["cases"][0]["passed"]
    assert report["cases"][0]["top_source_refs"] == ["linear:issue:ABC-123"]
    assert report["cases"][1]["found_expected_source_refs"] == []
    assert report["cases"][1]["found_expected_entities"] == []
    assert report["cases"][1]["failure_reason"] == (
        "missing_expected_source_refs,missing_expected_entities"
    )
