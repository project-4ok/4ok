from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql

from gcb.storage.models import Base
from gcb.storage.models.context_object import CanonicalObjectRow
from gcb.storage.models.entity_link import EntityLinkRow
from gcb.storage.models.source_record import SourceRecordRow


def test_storage_models_define_active_tables() -> None:
    assert {
        "source_records",
        "source_identities",
        "canonical_objects",
        "entity_links",
        "retrieval_records",
        "audit_events",
        "source_lifecycle",
        "connector_states",
        "connector_job_runs",
        "webhook_events",
    }.issubset(Base.metadata.tables)


def test_storage_models_compile_json_metadata_to_postgres_jsonb() -> None:
    dialect = postgresql.dialect()

    assert isinstance(
        SourceRecordRow.__table__.c.metadata_json.type.dialect_impl(dialect),
        postgresql.JSONB,
    )
    assert isinstance(
        CanonicalObjectRow.__table__.c.metadata_json.type.dialect_impl(dialect),
        postgresql.JSONB,
    )
    assert isinstance(
        EntityLinkRow.__table__.c.evidence_json.type.dialect_impl(dialect),
        postgresql.JSONB,
    )


def test_storage_model_tables_can_move_between_metadata_objects() -> None:
    metadata = MetaData()

    copied = SourceRecordRow.__table__.to_metadata(metadata)

    assert copied.name == "source_records"
    assert tuple(column.name for column in copied.columns) == tuple(
        column.name for column in SourceRecordRow.__table__.columns
    )
