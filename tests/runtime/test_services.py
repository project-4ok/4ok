from fourok.runtime.services import runtime_service_boundaries


def test_runtime_service_boundaries_cover_current_operational_surface() -> None:
    boundaries = runtime_service_boundaries()
    by_name = {boundary.name: boundary for boundary in boundaries}

    assert {
        "context-api",
        "connector-runner",
        "document-extraction-worker",
        "policy-engine",
        "metadata-database",
        "raw-source-store",
        "secrets-provider",
        "audit-store",
        "webhook-backlog",
    } <= by_name.keys()

    connector = by_name["connector-runner"]
    assert connector.current_runtime == "manual command"
    assert "stored checkpoints" in connector.responsibilities
    assert "job run history" in connector.responsibilities
    assert "bounded retry/backoff" in connector.responsibilities
    assert "per-connector running-job guard" in connector.responsibilities
    assert "production broker decision" in connector.not_yet
    assert "worker locking" not in connector.not_yet

    webhook_backlog = by_name["webhook-backlog"]
    assert webhook_backlog.current_runtime == "database-backed CLI worker"
    assert "idempotent event backlog" in webhook_backlog.responsibilities
    assert "production broker" in webhook_backlog.not_yet

    assert by_name["context-api"].health_check == "fourok health"
    assert "search_context" in by_name["context-api"].responsibilities
    assert "request_reveal" not in by_name["context-api"].responsibilities
    assert "controlled reveal" not in by_name["context-api"].not_yet

    policy_engine = by_name["policy-engine"]
    assert "source retrieval authorization" in policy_engine.responsibilities
    assert "field reveal authorization" not in policy_engine.responsibilities
    assert "PII/token reveal policy" in policy_engine.not_yet

    metadata_database = by_name["metadata-database"]
    assert "live restore-drill evidence" not in metadata_database.not_yet
    assert "backup scheduling" not in metadata_database.not_yet


def test_runtime_service_boundary_output_is_deterministic_and_json_ready() -> None:
    first = [boundary.to_dict() for boundary in runtime_service_boundaries()]
    second = [boundary.to_dict() for boundary in runtime_service_boundaries()]

    assert first == second
    assert first == sorted(first, key=lambda item: item["name"])
    assert all(
        set(item)
        == {
            "name",
            "current_runtime",
            "target_runtime",
            "responsibilities",
            "dependencies",
            "health_check",
            "not_yet",
        }
        for item in first
    )
