from pathlib import Path

from sqlalchemy import text

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.runtime.rebuild import rebuild_retrieval_units
from fourok.storage.config import RetrievalConfig


def test_rebuild_retrieval_units_rebuilds_vector_embeddings(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:EMBED-1",
                source_system="linear",
                source_id="EMBED-1",
                record_type="work_item",
                title="Embedding rebuild marker",
                body="Vector embedding rebuild should repopulate chunk embeddings.",
            )
        ]
    )

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    with state.engine.begin() as connection:
        connection.execute(text("delete from chunk_embeddings"))

    report = rebuild_retrieval_units(state, retrieval_config=RetrievalConfig())

    with state.engine.connect() as connection:
        embedded = connection.execute(text("select count(*) from chunk_embeddings")).scalar_one()

    assert report["retrieval_units_created"] == 1
    assert report["embeddings_indexed"] == 1
    assert embedded == 1
