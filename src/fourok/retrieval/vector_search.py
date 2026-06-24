from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.engine import Engine

from fourok.retrieval.embeddings import (
    cosine_similarity,
    embed_text,
    embedding_dimensions,
    vector_literal,
)


@dataclass(frozen=True)
class VectorSearchResult:
    source_ref: str
    chunk_index: int
    text: str
    score: float


class ChunkVectorIndex:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._create_schema()

    def index(self, chunks: list[dict[str, object]]) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("DELETE FROM chunk_embeddings"))
            self._insert_chunks(connection, chunks)

    def replace(self, source_refs: list[str], chunks: list[dict[str, object]]) -> None:
        if not source_refs:
            return

        with self._engine.begin() as connection:
            connection.execute(
                text("DELETE FROM chunk_embeddings WHERE source_ref IN :source_refs").bindparams(
                    bindparam("source_refs", expanding=True)
                ),
                {"source_refs": source_refs},
            )
            self._insert_chunks(connection, chunks)

    def search(self, query: str, *, limit: int = 5) -> list[VectorSearchResult]:
        query_embedding = embed_text(query)
        if self._engine.dialect.name == "postgresql":
            statement = text(
                """
                SELECT
                  source_ref,
                  chunk_index,
                  text,
                  1 - (embedding <=> CAST(:embedding AS vector)) AS score
                FROM chunk_embeddings
                ORDER BY embedding <=> CAST(:embedding AS vector), source_ref, chunk_index
                LIMIT :limit
                """
            )
            with self._engine.connect() as connection:
                rows = connection.execute(
                    statement,
                    {"embedding": vector_literal(query_embedding), "limit": limit},
                ).mappings()
                return [
                    VectorSearchResult(
                        source_ref=row["source_ref"],
                        chunk_index=row["chunk_index"],
                        text=row["text"],
                        score=float(row["score"]),
                    )
                    for row in rows
                ]

        with self._engine.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(text("SELECT * FROM chunk_embeddings")).mappings()
            ]

        scored = [
            VectorSearchResult(
                source_ref=row["source_ref"],
                chunk_index=row["chunk_index"],
                text=row["text"],
                score=cosine_similarity(query_embedding, json.loads(row["embedding"])),
            )
            for row in rows
        ]
        scored.sort(key=lambda result: (-result.score, result.source_ref, result.chunk_index))
        return scored[:limit]

    def stored_texts(self) -> list[str]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT text FROM chunk_embeddings ORDER BY source_ref, chunk_index")
            )
            return [row[0] for row in rows]

    def _create_schema(self) -> None:
        with self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                expected_dimensions = embedding_dimensions()
                existing_dimensions = _postgres_chunk_embedding_dimensions(connection)
                if existing_dimensions is not None and existing_dimensions != expected_dimensions:
                    connection.execute(text("DROP TABLE chunk_embeddings"))
                connection.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS chunk_embeddings (
                          source_ref TEXT NOT NULL,
                          chunk_index INTEGER NOT NULL,
                          text TEXT NOT NULL,
                          embedding vector({expected_dimensions}) NOT NULL,
                          PRIMARY KEY (source_ref, chunk_index)
                        )
                        """
                    )
                )
                return

            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chunk_embeddings (
                      source_ref TEXT NOT NULL,
                      chunk_index INTEGER NOT NULL,
                      text TEXT NOT NULL,
                      embedding TEXT NOT NULL,
                      PRIMARY KEY (source_ref, chunk_index)
                    )
                    """
                )
            )

    def _insert_chunks(self, connection, chunks: list[dict[str, object]]) -> None:
        for chunk in chunks:
            embedding = embed_text(str(chunk["body"]))
            if self._engine.dialect.name == "postgresql":
                connection.execute(
                    text(
                        """
                        INSERT INTO chunk_embeddings
                          (source_ref, chunk_index, text, embedding)
                        VALUES
                          (:source_ref, :chunk_index, :text, CAST(:embedding AS vector))
                        ON CONFLICT (source_ref, chunk_index) DO UPDATE SET
                          text = EXCLUDED.text,
                          embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "source_ref": chunk["source_ref"],
                        "chunk_index": chunk["chunk_index"],
                        "text": chunk["body"],
                        "embedding": vector_literal(embedding),
                    },
                )
            else:
                connection.execute(
                    text(
                        """
                        INSERT INTO chunk_embeddings
                          (source_ref, chunk_index, text, embedding)
                        VALUES
                          (:source_ref, :chunk_index, :text, :embedding)
                        ON CONFLICT (source_ref, chunk_index) DO UPDATE SET
                          text = excluded.text,
                          embedding = excluded.embedding
                        """
                    ),
                    {
                        "source_ref": chunk["source_ref"],
                        "chunk_index": chunk["chunk_index"],
                        "text": chunk["body"],
                        "embedding": json.dumps(embedding),
                    },
                )


def _postgres_chunk_embedding_dimensions(connection) -> int | None:
    if not inspect(connection).has_table("chunk_embeddings"):
        return None

    format_type = connection.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'chunk_embeddings'
              AND a.attname = 'embedding'
              AND n.nspname = current_schema()
            """
        )
    ).scalar_one_or_none()
    return _vector_dimension_from_type(format_type)


def _vector_dimension_from_type(format_type: object) -> int | None:
    if not isinstance(format_type, str):
        return None
    match = re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?vector\((\d+)\)", format_type.strip())
    if match is None:
        return None
    return int(match.group(1))
