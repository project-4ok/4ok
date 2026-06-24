from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.dialects import postgresql

from gcb.governance.state import create_governed_context_state
from gcb.storage.config import RawStoreConfig
from gcb.storage.models import (
    CanonicalObjectRow,
    EntityLinkRow,
    SourceRecordRow,
    table_for_model,
)
from gcb.storage.schema_contract import active_schema_contract


def test_create_governed_context_state_bootstraps_tables() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )

    assert state.engine.dialect.name == "sqlite"
    assert inspect(state.engine).has_table("emails")
    assert inspect(state.engine).has_table("email_chunks")
    assert not inspect(state.engine).has_table("token_store")
    assert not inspect(state.engine).has_table("token_sources")
    assert inspect(state.engine).has_table("audit_events")
    assert inspect(state.engine).has_table("connector_states")
    assert inspect(state.engine).has_table("connector_job_runs")
    assert inspect(state.engine).has_table("canonical_objects")
    assert inspect(state.engine).has_table("entity_links")
    assert inspect(state.engine).has_table("retrieval_records")
    assert state.raw_store is None


def test_active_schema_does_not_export_deferred_token_tables() -> None:
    assert "token_store" not in active_schema_contract()
    assert "token_sources" not in active_schema_contract()


def test_create_governed_context_state_configures_file_raw_store(tmp_path: Path) -> None:
    raw_store_path = tmp_path / "raw"

    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=raw_store_path,
    )

    assert state.raw_store is not None
    assert raw_store_path.exists()


def test_create_governed_context_state_configures_raw_store_from_config(
    tmp_path: Path,
) -> None:
    raw_store_path = tmp_path / "configured-raw"

    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
        raw_store_config=RawStoreConfig(backend="filesystem", path=raw_store_path),
    )

    assert state.raw_store is not None
    assert raw_store_path.exists()


def test_create_governed_context_state_does_not_patch_old_schema_in_app_code(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "old.sqlite"
    engine = create_engine(f"sqlite:///{state_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE source_lifecycle ("
                "source_ref VARCHAR PRIMARY KEY, "
                "state VARCHAR NOT NULL, "
                "reason TEXT NOT NULL DEFAULT '', "
                "recorded_at VARCHAR DEFAULT ''"
                ")"
            )
        )

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )

    columns = {
        column["name"]
        for column in inspect(create_engine(f"sqlite:///{state_path}")).get_columns(
            "source_lifecycle"
        )
    }
    assert {"replacement_ref", "duplicate_group_ref"}.isdisjoint(columns)
    assert state.source_lifecycle.c.replacement_ref.name == "replacement_ref"


def test_create_governed_context_state_rejects_unsupported_raw_store_backend() -> None:
    try:
        create_governed_context_state(
            state_path=":memory:",
            database_url=None,
            raw_store_path=None,
            raw_store_config=RawStoreConfig(backend="s3", path=Path("bucket/prefix")),
        )
    except ValueError as exc:
        assert str(exc) == "unsupported raw source store backend: s3"
    else:
        raise AssertionError("unsupported raw store backend should fail")


def test_metadata_columns_compile_to_postgres_jsonb() -> None:
    dialect = postgresql.dialect()
    metadata = MetaData()

    assert isinstance(
        table_for_model(metadata, SourceRecordRow.__table__).c.metadata_json.type.dialect_impl(
            dialect
        ),
        postgresql.JSONB,
    )
    assert isinstance(
        table_for_model(
            metadata,
            CanonicalObjectRow.__table__,
        ).c.metadata_json.type.dialect_impl(dialect),
        postgresql.JSONB,
    )
    assert isinstance(
        table_for_model(metadata, EntityLinkRow.__table__).c.evidence_json.type.dialect_impl(
            dialect
        ),
        postgresql.JSONB,
    )


def test_source_records_schema_enforces_source_identity_uniqueness() -> None:
    table = table_for_model(MetaData(), SourceRecordRow.__table__)

    assert {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if constraint.name == "uq_source_records_source_identity"
    } == {("source_system", "source_id")}
