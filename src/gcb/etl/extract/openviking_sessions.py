from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_openviking_session_messages_jsonl(sessions_dir: Path, messages_path: Path) -> int:
    if not sessions_dir.exists():
        raise FileNotFoundError(f"OpenViking sessions dir is not mounted: {sessions_dir}")
    count = 0
    with messages_path.open("w", encoding="utf-8") as output:
        for path in sorted(sessions_dir.glob("*topic-*.jsonl")):
            if any(
                marker in path.name
                for marker in (".trajectory", ".deleted", ".codex-app-server", ".reset")
            ):
                continue
            stem = path.name.removesuffix(".jsonl")
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = raw.get("message")
                if raw.get("type") != "message" or not isinstance(message, dict):
                    continue
                body = openviking_message_body(message.get("content"))
                if not body.strip():
                    continue
                normalized = {
                    "conversation_id": stem,
                    "session_id": stem,
                    "thread_id": stem,
                    "message_id": raw.get("id") or message.get("id"),
                    "timestamp": raw.get("timestamp") or message.get("timestamp"),
                    "message": {"role": message.get("role", "unknown"), "content": body},
                    "speaker": message.get("senderName")
                    or message.get("senderId")
                    or message.get("role", "unknown"),
                    "permission_refs": [f"openviking:conversation:{stem}"],
                }
                output.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                count += 1
    if count == 0:
        raise ValueError(f"No OpenViking messages found in {sessions_dir}")
    return count


def openviking_message_body(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts)
    return ""
