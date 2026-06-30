from __future__ import annotations

from sqlalchemy import create_engine

from fourok.etl.load import retrieval_records
from fourok.etl.load.retrieval_records import RetrievalRecord
from fourok.retrieval import embeddings
from fourok.retrieval.vector_search import ChunkVectorIndex


def test_replace_vector_index_initializes_when_chunk_table_is_absent(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    calls: list[tuple[list[str], list[dict[str, object]]]] = []

    class FakeChunkVectorIndex:
        def __init__(self, passed_engine):
            assert passed_engine is engine

        def replace(self, source_refs, chunks):
            calls.append((list(source_refs), list(chunks)))

    monkeypatch.setattr(retrieval_records, "ChunkVectorIndex", FakeChunkVectorIndex)

    retrieval_records.replace_vector_index_for_retrieval_records(
        engine,
        source_refs=["source:1"],
        records=[
            RetrievalRecord(
                retrieval_ref="retrieval:source:1:0",
                source_ref="source:1",
                unit_index=0,
                start_offset=0,
                end_offset=13,
                index_kind="text",
                status="current",
                source_checksum="abc",
                prepared_text="Prepared body",
                updated_at="2026-06-15T00:00:00Z",
            )
        ],
    )

    assert calls == [
        (
            ["source:1"],
            [{"source_ref": "source:1", "chunk_index": 0, "body": "Prepared body"}],
        )
    ]


def test_vector_index_replace_is_duplicate_safe_for_same_chunk() -> None:
    engine = create_engine("sqlite:///:memory:")
    index = ChunkVectorIndex(engine)

    index.replace(
        ["source:1"],
        [
            {"source_ref": "source:1", "chunk_index": 0, "body": "stale body"},
            {"source_ref": "source:1", "chunk_index": 0, "body": "fresh body"},
        ],
    )

    assert index.stored_texts() == ["fresh body"]


def test_vector_index_replace_batches_chunk_embedding(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    calls: list[list[str]] = []

    def fake_embed_texts(texts, *, dimensions=None):
        calls.append(list(texts))
        return [[float(index + 1)] * 32 for index, _text in enumerate(texts)]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed_texts)
    index = ChunkVectorIndex(engine)

    index.replace(
        ["source:1", "source:2"],
        [
            {"source_ref": "source:1", "chunk_index": 0, "body": "first body"},
            {"source_ref": "source:2", "chunk_index": 0, "body": "second body"},
        ],
    )

    assert calls == [["first body", "second body"]]
    assert index.stored_texts() == ["first body", "second body"]
