from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Integer, String, Text

from gcb.storage.models.base import Base


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token: Mapped[str] = mapped_column(String, nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String, nullable=False, default="")
    human_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    agent_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    decision: Mapped[str] = mapped_column(String, nullable=False, default="")
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    policy_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    policy_version: Mapped[str] = mapped_column(String, nullable=False, default="")
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_refs: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recorded_at: Mapped[str] = mapped_column(String, nullable=False, default="")
