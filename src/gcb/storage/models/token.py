from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import String, Text

from gcb.storage.models.base import Base


class TokenStoreRow(Base):
    __tablename__ = "token_store"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    token_type: Mapped[str] = mapped_column(String, nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)


class TokenSourceRow(Base):
    __tablename__ = "token_sources"

    source_ref: Mapped[str] = mapped_column(String, primary_key=True)
    token: Mapped[str] = mapped_column(String, primary_key=True)
