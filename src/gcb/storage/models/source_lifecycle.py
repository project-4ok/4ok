from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import String, Text

from gcb.storage.models.base import Base


class SourceLifecycleRow(Base):
    __tablename__ = "source_lifecycle"

    source_ref: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    replacement_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    duplicate_group_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    recorded_at: Mapped[str] = mapped_column(String, nullable=False, default="")
