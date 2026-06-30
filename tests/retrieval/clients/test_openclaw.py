from fourok.governance import GovernedContext
from fourok.retrieval.clients.openclaw import (
    OpenClawMessage,
    capture_openclaw_messages,
    openclaw_messages_to_source_records,
)


def test_openclaw_messages_become_message_source_records_without_control_boilerplate() -> None:
    records = openclaw_messages_to_source_records(
        [
            OpenClawMessage(
                session_id="session-1",
                agent_id="agent:claw",
                sender_id="user:olivia",
                role="user",
                content=(
                    "Conversation info (untrusted metadata): sender_id=user:olivia\n"
                    "Please remember the Robin Scharf renewal meeting."
                ),
                timestamp="2026-06-01T12:00:00+00:00",
                provider="openai",
                message_index=3,
            ),
            OpenClawMessage(
                session_id="session-1",
                agent_id="agent:claw",
                sender_id="agent:claw",
                role="assistant",
                content="I found the renewal context.",
                timestamp="2026-06-01T12:00:05+00:00",
                provider="openai",
                message_index=4,
            ),
        ]
    )

    assert [record.source_ref for record in records] == [
        "openclaw:session:session-1:message:000003",
        "openclaw:session:session-1:message:000004",
    ]
    assert records[0].source_system == "openclaw"
    assert records[0].record_type == "message"
    assert records[0].title == "OpenClaw user message in session-1"
    assert records[0].body == "Please remember the Robin Scharf renewal meeting."
    assert "Conversation info" not in records[0].body
    assert records[0].thread_ref == "openclaw:session:session-1"
    assert records[0].author_ref == "user:olivia"
    assert records[0].identity_refs == ("openclaw:sender:user:olivia",)
    assert records[0].metadata == {
        "session_id": "session-1",
        "agent_id": "agent:claw",
        "sender_id": "user:olivia",
        "role": "user",
        "provider": "openai",
        "message_index": 3,
        "source_object_type": "chat_message",
    }
    assert records[0].raw_ref == "openclaw:session:session-1:message:000003:raw"
    assert records[0].raw["content"].startswith("Conversation info")


def test_capture_openclaw_messages_imports_through_governed_pipeline(tmp_path) -> None:
    context = GovernedContext(tmp_path / "state.sqlite", raw_store_path=tmp_path / "raw")

    records = capture_openclaw_messages(
        context,
        [
            OpenClawMessage(
                session_id="session-1",
                agent_id="agent:claw",
                sender_id="user:olivia",
                role="user",
                content=(
                    "Conversation info (untrusted metadata): sender_id=user:olivia\n"
                    "Robin Scharf renewal meeting stays on Thursday."
                ),
                timestamp="2026-06-01T12:00:00+00:00",
                provider="openai",
                message_index=1,
            )
        ],
    )

    search = context.search_context("Robin renewal Thursday", limit=1)
    stored = context.source_records()[0]

    assert [record.source_ref for record in records] == [
        "openclaw:session:session-1:message:000001"
    ]
    assert search.result_candidates[0]["source_ref"] == (
        "openclaw:session:session-1:message:000001"
    )
    assert stored["record_type"] == "message"
    assert stored["raw_ref"] == "openclaw:session:session-1:message:000001:raw"
    assert "Conversation info" not in search.evidence_items[0]["snippet"]
    assert context.raw_source_refs() == ["openclaw:session:session-1:message:000001"]
