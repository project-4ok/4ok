from __future__ import annotations

from typing import Any

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import String, Text

from fourok.storage.models.base import JSON_DOCUMENT, Base


class SourceRecordRow(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("source_system", "source_id", name="uq_source_records_source_identity"),
    )

    source_ref: Mapped[str] = mapped_column(String, primary_key=True)
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    record_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retrieval_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    occurred_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    thread_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    permission_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    permission_snapshot_status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="current",
    )
    attachment_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    identity_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    lifecycle_state: Mapped[str] = mapped_column(String, nullable=False, default="active")
    checksum: Mapped[str] = mapped_column(String, nullable=False, default="")
    version: Mapped[str] = mapped_column(String, nullable=False, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    raw_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SourceIdentityRow(Base):
    __tablename__ = "source_identities"

    source_ref: Mapped[str] = mapped_column(String, primary_key=True)
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    identity_ref: Mapped[str] = mapped_column(String, primary_key=True)
    identity_type: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
