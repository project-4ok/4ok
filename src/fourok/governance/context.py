from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

from opentelemetry import trace

from fourok.etl.extract.email_parser import EmailMessage
from fourok.etl.extract.source_records import SourceRecord, email_message_to_source_record
from fourok.etl.load.context_objects import canonical_object_rows, entity_link_rows
from fourok.etl.load.retrieval_records import retrieval_record_rows
from fourok.etl.load.source_changes import (
    SourceChange,
    SourceChangeTables,
    apply_source_changes,
    upsert_source_records,
)
from fourok.etl.load.source_metadata import (
    denied_source_refs,
    source_identity_rows,
    source_record_rows,
)
from fourok.governance.audit import (
    audit_events,
    audit_summary,
    purge_expired_audit_events,
    record_audit_event,
)
from fourok.governance.indexing import (
    IndexingTables,
    raw_source_refs,
)
from fourok.governance.lifecycle import (
    inactive_source_refs,
    purge_expired_raw_sources,
    source_lifecycle_rows,
)
from fourok.governance.policy import PrincipalContext
from fourok.governance.state import create_governed_context_state
from fourok.observability import record_counter, record_histogram
from fourok.retrieval.augmentation import (
    DEFAULT_RETRIEVAL_TOKEN_BUDGET,
    RetrievalAugmentationResponse,
    RetrieverName,
    retrieve_augmentation,
)
from fourok.retrieval.evidence_pack import build_evidence_pack
from fourok.retrieval.search import SearchResult, snippet_for, source_record_search_rows
from fourok.retrieval.vector_search import ChunkVectorIndex
from fourok.storage.config import RawStoreConfig, RetrievalConfig


@dataclass(frozen=True)
class SearchContextResponse:
    results: list[SearchResult]
    query: str = ""
    summary: str = ""
    result_candidates: list[dict[str, object]] | None = None
    evidence_items: list[dict[str, object]] | None = None
    primary_objects: list[dict[str, object]] | None = None
    related_objects: list[dict[str, object]] | None = None
    related_object_groups: dict[str, list[dict[str, object]]] | None = None
    entities: list[dict[str, object]] | None = None
    unresolved_candidates: list[dict[str, object]] | None = None
    limitations: list[str] | None = None
    audit_ref: str = ""


class GovernedContext:
    def __init__(
        self,
        state_path: Path | str = ":memory:",
        *,
        database_url: str | None = None,
        raw_store_path: Path | str | None = None,
        raw_store_config: RawStoreConfig | None = None,
        retrieval_config: RetrievalConfig | None = None,
        group_inheritance: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        state = create_governed_context_state(
            state_path=state_path,
            database_url=database_url,
            raw_store_path=raw_store_path,
            raw_store_config=raw_store_config,
        )
        self._engine = state.engine
        self._metadata = state.metadata
        self._emails = state.emails
        self._chunks = state.chunks
        self._source_records = state.source_records
        self._source_identities = state.source_identities
        self._canonical_objects = state.canonical_objects
        self._entity_links = state.entity_links
        self._retrieval_records = state.retrieval_records
        self._audit_events = state.audit_events
        self._source_lifecycle = state.source_lifecycle
        self._raw_store = state.raw_store
        self._retrieval_config = retrieval_config or RetrievalConfig()
        self._indexing_tables = IndexingTables(
            emails=state.emails,
            chunks=state.chunks,
        )
        self._source_change_tables = SourceChangeTables(
            source_records=state.source_records,
            source_identities=state.source_identities,
            canonical_objects=state.canonical_objects,
            entity_links=state.entity_links,
            retrieval_records=state.retrieval_records,
            source_lifecycle=state.source_lifecycle,
            audit_events=state.audit_events,
            indexing=self._indexing_tables,
        )
        self._group_inheritance = group_inheritance or {}

    def ingest(self, messages: list[EmailMessage]) -> None:
        self.ingest_source_records(
            [email_message_to_source_record(message) for message in messages]
        )

    def ingest_source_records(self, records: list[SourceRecord]) -> None:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("fourok.source_records.ingest") as span:
            span.set_attribute("fourok.source_record.count", len(records))
            span.set_attribute(
                "fourok.source_record.source_systems",
                _joined_unique(record.source_system for record in records),
            )
            span.set_attribute(
                "fourok.source_record.record_types",
                _joined_unique(record.record_type for record in records),
            )
            try:
                self.apply_source_changes(upsert_source_records(records))
            except Exception as exc:
                span.set_attribute("fourok.source_record.status", "failed")
                span.set_attribute("fourok.error.class", type(exc).__name__)
                raise
            span.set_attribute("fourok.source_record.status", "succeeded")

    def apply_source_changes(
        self,
        changes: list[SourceChange],
        *,
        principal: PrincipalContext | None = None,
    ) -> None:
        apply_source_changes(
            self._engine,
            self._source_change_tables,
            changes=changes,
            raw_store=self._raw_store,
            principal=principal or PrincipalContext.local_default(),
            retrieval_max_words=self._retrieval_config.max_words,
            retrieval_overlap_words=self._retrieval_config.overlap_words,
        )

    def source_records(self) -> list[dict[str, object]]:
        return source_record_rows(self._engine, self._source_records)

    def source_identities(self) -> list[dict[str, object]]:
        return source_identity_rows(self._engine, self._source_identities)

    def canonical_objects(self) -> list[dict[str, object]]:
        return canonical_object_rows(self._engine, self._canonical_objects)

    def entity_links(self) -> list[dict[str, object]]:
        return entity_link_rows(self._engine, self._entity_links)

    def retrieval_units(self) -> list[dict[str, object]]:
        return retrieval_record_rows(self._engine, self._retrieval_records)

    def retrieve_augmentation(
        self,
        query: str,
        *,
        token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET,
        candidate_limit: int = 40,
        retrievers: tuple[RetrieverName, ...] = ("keyword", "vector"),
    ) -> RetrievalAugmentationResponse:
        return retrieve_augmentation(
            self._engine,
            self._source_records,
            self._retrieval_records,
            query,
            token_budget=token_budget,
            candidate_limit=candidate_limit,
            retrievers=retrievers,
        )

    def build_vector_index(self) -> ChunkVectorIndex:
        vector_index = ChunkVectorIndex(self._engine)
        vector_index.index(
            [
                {
                    "source_ref": unit["source_ref"],
                    "chunk_index": unit["unit_index"],
                    "body": unit["prepared_text"],
                }
                for unit in self.retrieval_units()
                if unit["status"] == "current"
            ]
        )
        return vector_index

    def restrict_source(
        self,
        source_ref: str,
        *,
        reason: str,
        principal: PrincipalContext | None = None,
    ) -> None:
        self.apply_source_changes(
            [SourceChange(operation="restrict", source_ref=source_ref, reason=reason)],
            principal=principal,
        )

    def delete_source(
        self,
        source_ref: str,
        *,
        reason: str,
        principal: PrincipalContext | None = None,
    ) -> None:
        self.apply_source_changes(
            [SourceChange(operation="delete", source_ref=source_ref, reason=reason)],
            principal=principal,
        )

    def source_lifecycle(self) -> list[dict[str, object]]:
        return source_lifecycle_rows(self._engine, self._source_lifecycle)

    def purge_expired_raw_sources(
        self,
        *,
        retention_days: int,
        now: datetime | None = None,
    ) -> list[str]:
        return purge_expired_raw_sources(
            self._engine,
            self._source_lifecycle,
            self._raw_store,
            retention_days=retention_days,
            now=now,
        )

    def raw_source_refs(self) -> list[str]:
        return raw_source_refs(self._raw_store)

    def search_context(
        self,
        query: str,
        *,
        limit: int = 5,
        principal: PrincipalContext | None = None,
    ) -> SearchContextResponse:
        tracer = trace.get_tracer(__name__)
        started = perf_counter()
        with tracer.start_as_current_span("fourok.search_context") as span:
            try:
                response = self._search_context_with_span(
                    query,
                    limit=limit,
                    principal=principal,
                    span=span,
                )
            except Exception:
                record_counter("fourok_search_requests_total", attributes={"status": "failed"})
                record_histogram("fourok_search_duration_seconds", perf_counter() - started)
                raise
            record_counter("fourok_search_requests_total", attributes={"status": "succeeded"})
            record_histogram("fourok_search_duration_seconds", perf_counter() - started)
            record_histogram("fourok_search_results", len(response.results))
            return response

    def _search_context_with_span(
        self,
        query: str,
        *,
        limit: int,
        principal: PrincipalContext | None,
        span,
    ) -> SearchContextResponse:
        span.set_attribute("fourok.search.limit", limit)
        span.set_attribute("fourok.search.query_length", len(query))
        principal_context = principal or PrincipalContext.local_default()
        denied_refs = denied_source_refs(
            self._engine,
            self._source_records,
            principal=principal_context,
            group_inheritance=self._group_inheritance,
        )
        span.set_attribute("fourok.search.denied_source_count", len(denied_refs))
        rows = source_record_search_rows(
            self._engine,
            self._source_records,
            self._retrieval_records,
            query,
            limit=limit,
            exclude_source_refs=denied_refs,
        )
        results = [
            SearchResult(
                source_ref=row["source_ref"],
                subject=row["subject"],
                date=row["date"],
                snippet=snippet_for(row["body"], query),
            )
            for row in rows
        ]
        audit_ref = self._record_audit(
            "search",
            {
                "query": query,
                "principal": principal_context,
                "result_count": len(results),
                "source_refs": [result.source_ref for result in results],
            },
        )
        if results:
            self._record_audit(
                "source_access",
                {
                    "query": query,
                    "principal": principal_context,
                    "decision": "allowed",
                    "result_count": len(results),
                    "source_refs": [result.source_ref for result in results],
                },
            )
        span.set_attribute("fourok.search.result_count", len(results))
        span.set_attribute("fourok.search.audit_recorded", bool(audit_ref))
        evidence_pack = build_evidence_pack(
            query=query,
            results=results,
            source_records=[
                row
                for row in self.source_records()
                if row["source_ref"] not in denied_refs and row["lifecycle_state"] == "active"
            ],
            canonical_objects=self.canonical_objects(),
            entity_links=self.entity_links(),
        )
        span.set_attribute(
            "fourok.search.evidence_item_count",
            len(evidence_pack.get("evidence_items", [])),
        )
        return SearchContextResponse(
            results=results,
            audit_ref=audit_ref,
            **evidence_pack,
        )

    def audit_events(
        self,
        *,
        event_type: str | None = None,
        source_ref: str | None = None,
        token: str | None = None,
        human_id: str | None = None,
    ) -> list[dict[str, object]]:
        return audit_events(
            self._engine,
            self._audit_events,
            event_type=event_type,
            source_ref=source_ref,
            token=token,
            human_id=human_id,
        )

    def audit_summary(self) -> dict[str, object]:
        return audit_summary(self._engine, self._audit_events)

    def purge_expired_audit_events(
        self,
        *,
        retention_days: int,
        now: datetime | None = None,
    ) -> int:
        return purge_expired_audit_events(
            self._engine,
            self._audit_events,
            retention_days=retention_days,
            now=now,
        )

    def _record_audit(self, event_type: str, values: dict[str, object]) -> str:
        return record_audit_event(self._engine, self._audit_events, event_type, values)

    def _inactive_source_refs(self) -> set[str]:
        return inactive_source_refs(self._engine, self._source_lifecycle)


def _joined_unique(values) -> str:
    return ",".join(sorted({str(value) for value in values if value}))
