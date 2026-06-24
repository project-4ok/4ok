from pathlib import Path

from sqlalchemy import delete

from fourok.etl.extract.email_parser import load_email_dir
from fourok.governance import GovernedContext
from fourok.retrieval.embeddings import chunk_text, embed_text, embedding_dimensions
from fourok.retrieval.evaluation import compare_retrieval_methods, load_retrieval_eval_cases
from fourok.retrieval.vector_search import _vector_dimension_from_type

FIXTURES = Path(__file__).parents[2] / "fixtures"
EMAILS = FIXTURES / "emails"
RETRIEVAL_EVAL = FIXTURES / "retrieval_eval" / "customer_context_queries.json"

RAW_SEEDED_VALUES = [
    "DE89370400440532013000",
    "anna.refunds@example.com",
    "+49 30 12345678",
    "finance+refunds@example.com",
    "+1 (415) 555-0134",
    "PMT-20260421",
    "DE89 3704 0044 0532 0130 00",
]


def test_chunk_text_splits_with_overlap() -> None:
    chunks = chunk_text(
        " ".join(f"word{index}" for index in range(12)), max_words=5, overlap_words=2
    )

    assert [chunk.text for chunk in chunks] == [
        "word0 word1 word2 word3 word4",
        "word3 word4 word5 word6 word7",
        "word6 word7 word8 word9 word10",
        "word9 word10 word11",
    ]


def test_embeddings_are_deterministic_and_normalized() -> None:
    first = embed_text("refund cancellation payment")
    second = embed_text("refund cancellation payment")

    assert first == second
    assert round(sum(value * value for value in first), 6) == 1.0


def test_openai_embedding_provider_uses_api_when_key_is_configured(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return b'{"data":[{"embedding":[0.1,0.2,0.3,0.4]}]}'

    def fake_urlopen(request, timeout):
        requests.append({"request": request, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FOUR_OK_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("FOUR_OK_EMBEDDING_DIMENSIONS", "4")
    monkeypatch.setattr("fourok.retrieval.embeddings._urlopen", fake_urlopen)

    assert embedding_dimensions() == 4
    assert embed_text("runtime deployment decision") == [0.1, 0.2, 0.3, 0.4]
    assert requests
    request = requests[0]["request"]
    assert request.get_header("Authorization") == "Bearer test-key"
    assert requests[0]["timeout"] == 30


def test_vector_dimension_parser_detects_existing_pgvector_width() -> None:
    assert _vector_dimension_from_type("vector(32)") == 32
    assert _vector_dimension_from_type("public.vector(256)") == 256
    assert _vector_dimension_from_type("USER-DEFINED") is None


def test_governed_context_prepares_raw_internal_retrieval_units_for_now() -> None:
    context = GovernedContext()
    context.ingest(load_email_dir(EMAILS))

    serialized_units = " ".join(str(unit) for unit in context.retrieval_units())

    assert "BANK_ACCOUNT_" not in serialized_units
    assert any(raw_value in serialized_units for raw_value in RAW_SEEDED_VALUES)


def test_retrieval_quality_loop_compares_full_text_vector_and_hybrid() -> None:
    context = GovernedContext()
    context.ingest(load_email_dir(EMAILS))
    vector_index = context.build_vector_index()
    cases = load_retrieval_eval_cases(RETRIEVAL_EVAL)

    metrics = compare_retrieval_methods(context, vector_index, cases)

    by_method = {metric.method: metric for metric in metrics}
    assert set(by_method) == {"full_text", "vector", "hybrid"}
    assert by_method["full_text"].top3_hits >= 8
    assert by_method["vector"].top3_hits >= 7
    assert by_method["hybrid"].top3_hits >= 8
    stored_vector_text = " ".join(vector_index.stored_texts())
    assert any(raw_value in stored_vector_text for raw_value in RAW_SEEDED_VALUES)


def test_vector_index_builds_from_retrieval_units_without_legacy_email_chunks() -> None:
    context = GovernedContext()
    context.ingest(load_email_dir(EMAILS))

    with context._engine.begin() as connection:
        connection.execute(delete(context._chunks))

    vector_index = context.build_vector_index()

    assert not hasattr(context, "email_compatibility_chunks")
    stored_text = " ".join(vector_index.stored_texts())
    assert any(raw_value in stored_text for raw_value in RAW_SEEDED_VALUES)
