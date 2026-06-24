from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import MetaData, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from gcb.storage.models import (
    AuditEventRow,
    CanonicalObjectRow,
    ConnectorJobRunRow,
    ConnectorStateRow,
    EntityLinkRow,
    RetrievalRecordRow,
    SourceIdentityRow,
    SourceLifecycleRow,
    SourceRecordRow,
    WebhookEventRow,
    table_for_model,
)

ACTIVE_TABLES: tuple[Table, ...] = (
    SourceRecordRow.__table__,
    SourceIdentityRow.__table__,
    RetrievalRecordRow.__table__,
    CanonicalObjectRow.__table__,
    EntityLinkRow.__table__,
    AuditEventRow.__table__,
    SourceLifecycleRow.__table__,
    ConnectorStateRow.__table__,
    ConnectorJobRunRow.__table__,
    WebhookEventRow.__table__,
)


def active_table_factories() -> tuple[Callable[[MetaData], Table], ...]:
    return tuple(
        lambda metadata, table=table: table_for_model(metadata, table) for table in ACTIVE_TABLES
    )


def active_schema_contract() -> dict[str, tuple[str, ...]]:
    metadata = MetaData()
    return {
        table.name: tuple(column.name for column in table.columns)
        for table in (factory(metadata) for factory in active_table_factories())
    }


def check_active_schema_contract(engine: Engine) -> dict[str, object]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    contract = active_schema_contract()
    missing_tables = [table for table in contract if table not in table_names]
    missing_columns = {
        table: [
            column
            for column in columns
            if column not in {stored["name"] for stored in inspector.get_columns(table)}
        ]
        for table, columns in contract.items()
        if table in table_names
    }
    missing_columns = {table: columns for table, columns in missing_columns.items() if columns}
    status = "ok" if not missing_tables and not missing_columns else "failed"
    return {
        "status": status,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
    }
