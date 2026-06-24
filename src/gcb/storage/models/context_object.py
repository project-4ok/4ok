from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import String, Text

from gcb.storage.models.base import JSON_DOCUMENT, Base


class CanonicalObjectRow(Base):
    __tablename__ = "canonical_objects"

    object_ref: Mapped[str] = mapped_column(String, primary_key=True)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    lifecycle_state: Mapped[str] = mapped_column(String, nullable=False, default="active")
