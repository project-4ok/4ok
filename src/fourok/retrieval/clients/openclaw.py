from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import trace

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext


@dataclass(frozen=True)
class OpenClawMessage:
    session_id: str
    agent_id: str
    sender_id: str
    role: str
    content: str
    timestamp: str
    provider: str
    message_index: int


def capture_openclaw_messages(
    context: GovernedContext,
    messages: list[OpenClawMessage],
) -> list[SourceRecord]:
    records = openclaw_messages_to_source_records(messages)
    context.ingest_source_records(records)
    return records


def openclaw_messages_to_source_records(messages: list[OpenClawMessage]) -> list[SourceRecord]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("fourok.openclaw.capture") as span:
        records = [_openclaw_message_to_source_record(message) for message in messages]
        span.set_attribute("fourok.openclaw.message_count", len(messages))
        span.set_attribute("fourok.openclaw.record_count", len(records))
        span.set_attribute(
            "fourok.openclaw.session_count",
            len({message.session_id for message in messages}),
        )
        return records


def _openclaw_message_to_source_record(message: OpenClawMessage) -> SourceRecord:
    source_ref = f"openclaw:session:{message.session_id}:message:{message.message_index:06d}"
    source_id = f"{message.session_id}:{message.message_index}"
    raw_ref = f"{source_ref}:raw"
    return SourceRecord(
        source_ref=source_ref,
        source_system="openclaw",
        source_id=source_id,
        record_type="message",
        title=f"OpenClaw {message.role} message in {message.session_id}",
        body=_strip_openclaw_boilerplate(message.content),
        occurred_at=message.timestamp,
        updated_at=message.timestamp,
        author_ref=message.sender_id,
        thread_ref=f"openclaw:session:{message.session_id}",
        identity_refs=(f"openclaw:sender:{message.sender_id}",) if message.sender_id else (),
        metadata={
            "session_id": message.session_id,
            "agent_id": message.agent_id,
            "sender_id": message.sender_id,
            "role": message.role,
            "provider": message.provider,
            "message_index": message.message_index,
            "source_object_type": "chat_message",
        },
        raw={
            "session_id": message.session_id,
            "agent_id": message.agent_id,
            "sender_id": message.sender_id,
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp,
            "provider": message.provider,
            "message_index": message.message_index,
        },
        raw_ref=raw_ref,
    )


def _strip_openclaw_boilerplate(content: str) -> str:
    lines = content.splitlines()
    kept: list[str] = []
    skipping_untrusted_block = False
    for line in lines:
        if line.startswith("Conversation info (untrusted metadata):"):
            skipping_untrusted_block = True
            continue
        if skipping_untrusted_block and _looks_like_metadata_line(line):
            continue
        skipping_untrusted_block = False
        if _is_control_boilerplate(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _looks_like_metadata_line(line: str) -> bool:
    if not line.strip():
        return True
    return "=" in line or ":" in line and len(line.split()) <= 4


def _is_control_boilerplate(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return stripped in {"HEARTBEAT_OK"} or stripped.startswith("<system-reminder>")
