from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.schema import Table

from fourok.retrieval.search import chunk_table, email_table
from fourok.storage.config import RawStoreConfig
from fourok.storage.models import (
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
from fourok.storage.raw_store import FileRawSourceStore, raw_source_store_from_config


@dataclass(frozen=True)
class GovernedContextState:
    engine: Engine
    metadata: MetaData
    emails: Table
    chunks: Table
    source_records: Table
    source_identities: Table
    canonical_objects: Table
    entity_links: Table
    retrieval_records: Table
    audit_events: Table
    source_lifecycle: Table
    connector_states: Table
    connector_job_runs: Table
    webhook_events: Table
    raw_store: FileRawSourceStore | None


def create_governed_context_state(
    *,
    state_path: Path | str,
    database_url: str | None,
    raw_store_path: Path | str | None,
    raw_store_config: RawStoreConfig | None = None,
) -> GovernedContextState:
    engine = _create_engine(state_path=state_path, database_url=database_url)
    metadata = MetaData()
    state = GovernedContextState(
        engine=engine,
        metadata=metadata,
        emails=email_table(metadata),
        chunks=chunk_table(metadata),
        source_records=table_for_model(metadata, SourceRecordRow.__table__),
        source_identities=table_for_model(metadata, SourceIdentityRow.__table__),
        canonical_objects=table_for_model(metadata, CanonicalObjectRow.__table__),
        entity_links=table_for_model(metadata, EntityLinkRow.__table__),
        retrieval_records=table_for_model(metadata, RetrievalRecordRow.__table__),
        audit_events=table_for_model(metadata, AuditEventRow.__table__),
        source_lifecycle=table_for_model(metadata, SourceLifecycleRow.__table__),
        connector_states=table_for_model(metadata, ConnectorStateRow.__table__),
        connector_job_runs=table_for_model(metadata, ConnectorJobRunRow.__table__),
        webhook_events=table_for_model(metadata, WebhookEventRow.__table__),
        raw_store=_raw_store(raw_store_path=raw_store_path, raw_store_config=raw_store_config),
    )
    metadata.create_all(engine)
    return state


def _raw_store(
    *,
    raw_store_path: Path | str | None,
    raw_store_config: RawStoreConfig | None,
) -> FileRawSourceStore | None:
    if raw_store_path is not None:
        return FileRawSourceStore(Path(raw_store_path))
    if raw_store_config is not None:
        return raw_source_store_from_config(raw_store_config)
    return None


def _sqlite_url(state_path: Path | str) -> str:
    if str(state_path) == ":memory:":
        return "sqlite:///:memory:"
    path = Path(state_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def _database_url(*, state_path: Path | str, database_url: str | None) -> str:
    if database_url:
        return database_url
    state = str(state_path)
    if "://" in state:
        return state
    return _sqlite_url(state_path)


def _create_engine(*, state_path: Path | str, database_url: str | None) -> Engine:
    url = _database_url(state_path=state_path, database_url=database_url)
    if url == "sqlite:///:memory:":
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url)
