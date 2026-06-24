from gcb.etl.extract.source_records import SourceRecord
from gcb.retrieval.context_eval import evaluate_governed_context_retrieval


def test_governed_context_eval_fails_on_unacceptable_source_refs() -> None:
    report = evaluate_governed_context_retrieval(
        [
            SourceRecord(
                source_ref="linear:issue:expected",
                source_system="linear",
                source_id="expected",
                record_type="work_item",
                title="Customer portal renewal",
                body="Customer portal renewal needs approval.",
            ),
            SourceRecord(
                source_ref="linear:issue:wrong",
                source_system="linear",
                source_id="wrong",
                record_type="work_item",
                title="Customer portal renewal",
                body="Customer portal renewal stale duplicate.",
            ),
        ],
        [
            {
                "id": "false_positive_guard",
                "query": "customer portal renewal",
                "expected_source_refs": ["linear:issue:expected"],
                "unacceptable_source_refs": ["linear:issue:wrong"],
            }
        ],
        limit=2,
    )

    assert report["status"] == "needs_review"
    assert report["summary"]["unacceptable_source_checks"] == 1
    assert report["summary"]["unacceptable_source_violations"] == 1
    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failure_reason"] == "found_unacceptable_source_refs"
    assert report["cases"][0]["found_unacceptable_source_refs"] == ["linear:issue:wrong"]
