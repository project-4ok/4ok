from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.schema import MetaData, Table
from sqlalchemy.sql.sqltypes import JSON


class Base(DeclarativeBase):
    pass


JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


def table_for_model(metadata: MetaData, table: Table) -> Table:
    if table.name in metadata.tables:
        return metadata.tables[table.name]
    return table.to_metadata(metadata)
