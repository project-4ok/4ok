from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    Column,
    MetaData,
    Table,
    bindparam,
    desc,
    func,
    literal,
    literal_column,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Integer, String, Text


@dataclass(frozen=True)
class SearchResult:
    source_ref: str
    subject: str
    date: str
    snippet: str


def email_table(metadata: MetaData) -> Table:
    return Table(
        "emails",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("source_ref", String, nullable=False),
        Column("subject", String, nullable=False, default=""),
        Column("body", Text, nullable=False, default=""),
        Column("date", String, nullable=False, default=""),
    )


def chunk_table(metadata: MetaData) -> Table:
    return Table(
        "email_chunks",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("source_ref", String, nullable=False),
        Column("chunk_index", Integer, nullable=False),
        Column("subject", String, nullable=False, default=""),
        Column("body", Text, nullable=False, default=""),
        Column("date", String, nullable=False, default=""),
    )


def source_record_search_rows(
    engine: Engine,
    source_records: Table,
    retrieval_records: Table,
    query: str,
    *,
    limit: int,
    exclude_source_refs: set[str] | None = None,
) -> list[dict[str, str]]:
    if limit < 1:
        return []
    if engine.dialect.name == "postgresql":
        return _postgres_source_record_search_rows(
            engine,
            source_records,
            retrieval_records,
            query,
            limit=limit,
            exclude_source_refs=exclude_source_refs or set(),
        )
    return _python_source_record_search_rows(
        engine,
        source_records,
        retrieval_records,
        query,
        limit=limit,
        exclude_source_refs=exclude_source_refs or set(),
    )


def _python_source_record_search_rows(
    engine: Engine,
    source_records: Table,
    retrieval_records: Table,
    query: str,
    *,
    limit: int,
    exclude_source_refs: set[str],
) -> list[dict[str, str]]:
    terms = query_terms(query)
    statement = (
        select(
            source_records.c.source_ref,
            source_records.c.title,
            source_records.c.occurred_at,
            retrieval_records.c.prepared_text,
            retrieval_records.c.unit_index,
        )
        .select_from(
            retrieval_records.join(
                source_records,
                retrieval_records.c.source_ref == source_records.c.source_ref,
            )
        )
        .where(retrieval_records.c.status == "current")
        .where(source_records.c.lifecycle_state == "active")
    )
    if exclude_source_refs:
        statement = statement.where(source_records.c.source_ref.not_in(exclude_source_refs))
    with engine.connect() as connection:
        rows = [dict(row) for row in connection.execute(statement).mappings()]

    scored_rows = [
        (score, row) for row in rows if (score := _retrieval_record_match_score(row, terms)) > 0
    ]
    scored_rows.sort(
        key=lambda item: (
            -item[0],
            str(item[1]["occurred_at"]),
            str(item[1]["source_ref"]),
            int(item[1]["unit_index"]),
        )
    )
    return [_retrieval_record_row_to_search_row(row) for _, row in scored_rows[:limit]]


def _postgres_source_record_search_rows(
    engine: Engine,
    source_records: Table,
    retrieval_records: Table,
    query: str,
    *,
    limit: int,
    exclude_source_refs: set[str],
) -> list[dict[str, str]]:
    statement = postgres_source_record_search_statement(
        source_records,
        retrieval_records,
        query,
        limit=limit,
        exclude_source_refs=exclude_source_refs,
    )
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement, {"exclude_source_refs": list(exclude_source_refs)}
            ).mappings()
        ]


def postgres_source_record_search_statement(
    source_records: Table,
    retrieval_records: Table,
    query: str,
    *,
    limit: int,
    exclude_source_refs: set[str] | None = None,
):
    query_terms(query)
    english_config = literal_column("'english'::regconfig")
    body = func.concat(
        source_records.c.title,
        literal(" "),
        retrieval_records.c.prepared_text,
        literal(" "),
        source_records.c.source_ref,
    )
    document = func.to_tsvector(english_config, body)
    parsed_query = func.plainto_tsquery(english_config, query)
    rank = func.ts_rank(document, parsed_query).label("rank")
    statement = (
        select(
            source_records.c.source_ref,
            source_records.c.title.label("subject"),
            retrieval_records.c.prepared_text.label("body"),
            source_records.c.occurred_at.label("date"),
        )
        .select_from(
            retrieval_records.join(
                source_records,
                retrieval_records.c.source_ref == source_records.c.source_ref,
            )
        )
        .where(retrieval_records.c.status == "current")
        .where(source_records.c.lifecycle_state == "active")
        .where(document.op("@@")(parsed_query))
        .order_by(
            desc(rank),
            source_records.c.occurred_at,
            source_records.c.source_ref,
            retrieval_records.c.unit_index,
        )
        .limit(limit)
    )
    if exclude_source_refs:
        statement = statement.where(
            source_records.c.source_ref.not_in(bindparam("exclude_source_refs", expanding=True))
        )
    return statement


def _retrieval_record_row_to_search_row(row: dict[str, object]) -> dict[str, str]:
    title = str(row["title"])
    prepared_text = str(row["prepared_text"])
    return {
        "source_ref": str(row["source_ref"]),
        "subject": title,
        "body": _snippet_text(prepared_text, title),
        "date": str(row["occurred_at"]),
    }


def _snippet_text(prepared_text: str, title: str) -> str:
    prefix = f"{title} "
    if title and prepared_text.startswith(prefix):
        return prepared_text.removeprefix(prefix)
    return prepared_text


def query_terms(query: str) -> list[str]:
    terms = [term.strip().lower().strip('"') for term in query.split() if term.strip()]
    if not terms:
        raise ValueError("Search query must not be empty.")
    return terms


def snippet_for(text: str, query: str, *, window: int = 160) -> str:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return ""

    lower_text = normalized_text.lower()
    first_index = min(
        (index for term in query_terms(query) if (index := lower_text.find(term)) >= 0),
        default=0,
    )
    start = max(first_index - window // 2, 0)
    end = min(start + window, len(normalized_text))
    snippet = normalized_text[start:end].strip()
    if start > 0:
        snippet = f"... {snippet}"
    if end < len(normalized_text):
        snippet = f"{snippet} ..."
    return snippet


def _match_score(subject: str, body: str, terms: list[str]) -> int:
    haystack = f"{subject} {body}".lower()
    return sum(haystack.count(term) for term in terms)


def _retrieval_record_match_score(row: dict[str, object], terms: list[str]) -> int:
    return _match_score(
        str(row["title"]),
        " ".join([str(row["prepared_text"]), str(row["source_ref"])]),
        terms,
    )
