"""Deferred token-store experiment.

The active internal runtime searches raw source-record text. This module stays
available for isolated tests and later governance work, but it is not part of
the current import/search path.
"""

from __future__ import annotations

import re

from sqlalchemy import MetaData, Table, delete, insert, select
from sqlalchemy.engine import Engine

from fourok.etl.transform.tokens import deterministic_token, normalize_token_value
from fourok.storage.models.token import TokenSourceRow, TokenStoreRow


def _table_for_model(metadata: MetaData, table: Table) -> Table:
    if table.name in metadata.tables:
        return metadata.tables[table.name]
    return table.to_metadata(metadata)


def token_store_table(metadata: MetaData) -> Table:
    return _table_for_model(metadata, TokenStoreRow.__table__)


def token_sources_table(metadata: MetaData) -> Table:
    return _table_for_model(metadata, TokenSourceRow.__table__)


def token_for(
    engine: Engine,
    token_store: Table,
    *,
    token_type: str,
    raw_value: str,
) -> str:
    normalized_value = normalize_token_value(token_type=token_type, raw_value=raw_value)
    token = deterministic_token(token_type=token_type, normalized_value=normalized_value)
    existing = find_token_row(engine, token_store, token)
    if existing:
        return token

    with engine.begin() as connection:
        connection.execute(
            insert(token_store).values(
                token=token,
                token_type=token_type,
                raw_value=raw_value,
                normalized_value=normalized_value,
            )
        )
    return token


def find_token_row(engine: Engine, token_store: Table, token: str) -> dict[str, str] | None:
    statement = select(token_store).where(token_store.c.token == token)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def token_row_by_value(
    engine: Engine,
    token_store: Table,
    *,
    token_type: str,
    raw_value: str,
) -> dict[str, str] | None:
    normalized_value = normalize_token_value(token_type=token_type, raw_value=raw_value)
    statement = select(token_store).where(
        token_store.c.token_type == token_type,
        token_store.c.normalized_value == normalized_value,
    )
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def tokens_for_rows(
    engine: Engine,
    token_store: Table,
    rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    text = " ".join(part for row in rows for part in [row["subject"], row["body"]] if part)
    tokens = sorted(set(re.findall(r"\b[A-Z_]+_[A-F0-9]{16}\b", text)))
    if not tokens:
        return []

    statement = (
        select(token_store.c.token, token_store.c.token_type)
        .where(token_store.c.token.in_(tokens))
        .order_by(token_store.c.token)
    )
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings()
        return [{"token": row["token"], "type": row["token_type"]} for row in rows]


def prune_unreferenced_tokens(connection, token_store: Table, token_sources: Table) -> None:
    referenced_tokens = select(token_sources.c.token)
    connection.execute(delete(token_store).where(token_store.c.token.not_in(referenced_tokens)))
