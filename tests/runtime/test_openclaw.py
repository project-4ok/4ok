from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext
from fourok.runtime.openclaw import (
    OpenClawMessage,
    OpenClawSearchTools,
    call_openclaw_tool,
    capture_openclaw_messages,
    openclaw_messages_to_source_records,
    openclaw_tool_contracts,
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


def test_openclaw_search_tools_expose_only_fourok_search_context() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        openclaw_messages_to_source_records(
            [
                OpenClawMessage(
                    session_id="session-1",
                    agent_id="agent:claw",
                    sender_id="user:olivia",
                    role="user",
                    content="Robin Scharf renewal meeting is on Thursday.",
                    timestamp="2026-06-01T12:00:00+00:00",
                    provider="openai",
                    message_index=1,
                )
            ]
        )
    )
    tools = OpenClawSearchTools(
        context,
        PrincipalContext(
            human_id="human:olivia",
            agent_id="agent:claw",
            roles=("operator",),
        ),
    )

    public_methods = {
        name for name in dir(tools) if not name.startswith("_") and callable(getattr(tools, name))
    }
    response = tools.fourok_search_context("Robin renewal", limit=1)

    assert public_methods == {"fourok_search_context"}
    assert response["result_candidates"][0]["source_ref"] == (
        "openclaw:session:session-1:message:000001"
    )
    assert response["evidence_items"][0]["source_type"] == "Message"
    assert "request_reveal" not in public_methods
    assert "reveal" not in str(response).casefold()


def test_openclaw_tool_contract_exposes_only_search_context_schema() -> None:
    contracts = openclaw_tool_contracts()

    assert [contract["name"] for contract in contracts] == ["fourok_search_context"]
    assert contracts[0] == {
        "name": "fourok_search_context",
        "description": (
            "Search governed company context and return permission-filtered evidence. "
            "Does not return hidden fields or inject context automatically."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Search query for governed context evidence.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Maximum number of primary evidence candidates.",
                },
            },
        },
    }
    assert "reveal" not in str(contracts).casefold()
    assert "prompt" not in str(contracts).casefold()


def test_openclaw_tool_dispatch_validates_arguments_and_invokes_search() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        openclaw_messages_to_source_records(
            [
                OpenClawMessage(
                    session_id="session-1",
                    agent_id="agent:claw",
                    sender_id="user:olivia",
                    role="user",
                    content="Robin Scharf renewal meeting is on Thursday.",
                    timestamp="2026-06-01T12:00:00+00:00",
                    provider="openai",
                    message_index=1,
                )
            ]
        )
    )
    tools = OpenClawSearchTools(
        context,
        PrincipalContext(
            human_id="human:olivia",
            agent_id="agent:claw",
            roles=("operator",),
        ),
    )

    response = call_openclaw_tool(
        tools,
        "fourok_search_context",
        {"query": "Robin renewal", "limit": 1},
    )

    assert response["result_candidates"][0]["source_ref"] == (
        "openclaw:session:session-1:message:000001"
    )
    assert response["audit_ref"].startswith("audit:search:")


def test_openclaw_tool_dispatch_rejects_unknown_tools_and_bad_arguments() -> None:
    tools = OpenClawSearchTools(
        GovernedContext(),
        PrincipalContext(
            human_id="human:olivia",
            agent_id="agent:claw",
            roles=("operator",),
        ),
    )

    try:
        call_openclaw_tool(tools, "request_reveal", {"token": "BANK_ACCOUNT_1"})
    except ValueError as exc:
        assert str(exc) == "unsupported OpenClaw 4OK tool: request_reveal"
    else:
        raise AssertionError("unknown tool should be rejected")

    try:
        call_openclaw_tool(tools, "fourok_search_context", {"query": "", "limit": 1})
    except ValueError as exc:
        assert str(exc) == "fourok_search_context.query must be a non-empty string"
    else:
        raise AssertionError("empty query should be rejected")

    try:
        call_openclaw_tool(tools, "fourok_search_context", {"query": "Robin", "limit": 100})
    except ValueError as exc:
        assert str(exc) == "fourok_search_context.limit must be between 1 and 20"
    else:
        raise AssertionError("invalid limit should be rejected")
