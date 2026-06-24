from __future__ import annotations

from typing import Any

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Integer, String, Text

from gcb.storage.models.base import JSON_DOCUMENT, Base


class WebhookEventRow(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_webhook_events_idempotency_key"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    source_object_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    received_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    actor_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    raw_payload_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    error_class: Mapped[str] = mapped_column(String, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    processed_at: Mapped[str] = mapped_column(String, nullable=False, default="")
