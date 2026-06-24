from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Integer, String, Text

from gcb.storage.models.base import Base


class RetrievalRecordRow(Base):
    __tablename__ = "retrieval_records"

    retrieval_ref: Mapped[str] = mapped_column(String, primary_key=True)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="current")
    source_checksum: Mapped[str] = mapped_column(String, nullable=False, default="")
    prepared_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default="")
