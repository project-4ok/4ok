from sqlalchemy import MetaData, create_engine, insert, select
from sqlalchemy.sql.schema import Table

from gcb.governance.token_store import (
    find_token_row,
    prune_unreferenced_tokens,
    token_for,
    token_row_by_value,
    token_sources_table,
    token_store_table,
    tokens_for_rows,
)
from gcb.storage.models.token import TokenSourceRow, TokenStoreRow


def test_token_tables_are_backed_by_orm_models() -> None:
    metadata = MetaData()

    assert isinstance(token_store_table(metadata), Table)
    assert token_store_table(metadata).name == TokenStoreRow.__tablename__
    assert token_sources_table(metadata).name == TokenSourceRow.__tablename__


def build_token_store():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    token_store = token_store_table(metadata)
    token_sources = token_sources_table(metadata)
    metadata.create_all(engine)
    return engine, token_store, token_sources


def test_token_for_stores_and_reuses_deterministic_token() -> None:
    engine, token_store, _ = build_token_store()

    first = token_for(engine, token_store, token_type="email", raw_value="Anna@example.com")
    second = token_for(engine, token_store, token_type="email", raw_value="anna@example.com")

    assert first == second
    assert find_token_row(engine, token_store, first) == {
        "token": first,
        "token_type": "email",
        "raw_value": "Anna@example.com",
        "normalized_value": "ANNA@EXAMPLE.COM",
    }
    assert (
        token_row_by_value(engine, token_store, token_type="email", raw_value="anna@example.com")[
            "token"
        ]
        == first
    )


def test_tokens_for_rows_returns_token_metadata_from_sanitized_rows() -> None:
    engine, token_store, _ = build_token_store()
    email_token = token_for(engine, token_store, token_type="email", raw_value="a@example.com")
    phone_token = token_for(engine, token_store, token_type="phone", raw_value="+49 30 123456")

    tokens = tokens_for_rows(
        engine,
        token_store,
        [
            {"subject": f"Contact {email_token}", "body": "nothing"},
            {"subject": "Phone", "body": f"Use {phone_token}"},
        ],
    )

    assert tokens == [
        {"token": email_token, "type": "email"},
        {"token": phone_token, "type": "phone"},
    ]


def test_prune_unreferenced_tokens_removes_only_orphans() -> None:
    engine, token_store, token_sources = build_token_store()
    kept = token_for(engine, token_store, token_type="email", raw_value="kept@example.com")
    removed = token_for(engine, token_store, token_type="email", raw_value="removed@example.com")

    with engine.begin() as connection:
        connection.execute(insert(token_sources).values(source_ref="source:1", token=kept))
        prune_unreferenced_tokens(connection, token_store, token_sources)

    with engine.connect() as connection:
        tokens = {row[0] for row in connection.execute(select(token_store.c.token)).fetchall()}
    assert tokens == {kept}
    assert removed not in tokens
