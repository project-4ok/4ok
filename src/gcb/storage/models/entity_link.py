from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Float, String, Text

from gcb.storage.models.base import JSON_DOCUMENT, Base


class EntityLinkRow(Base):
    __tablename__ = "entity_links"

    link_ref: Mapped[str] = mapped_column(String, primary_key=True)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    object_ref: Mapped[str] = mapped_column(String, nullable=False)
    relationship_type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="candidate")
