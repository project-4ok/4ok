from __future__ import annotations

import sqlite3

from sqlalchemy import inspect, text

Metric = tuple[str, dict[str, str], float]


def embedding_coverage_metrics_sqlite(connection: sqlite3.Connection) -> list[Metric]:
    retrieval_columns = _sqlite_columns(connection, "retrieval_records")
    unit_index_expr = "r.unit_index" if "unit_index" in retrieval_columns else "0"
    total = float(
        connection.execute(
            "select count(*) from retrieval_records where status = 'current'"
        ).fetchone()[0]
        or 0
    )
    if not _has_table(connection, "chunk_embeddings"):
        return _embedding_coverage_metrics(total=total, embedded=0.0)

    embedded = float(
        connection.execute(
            f"""
            select count(*)
            from retrieval_records r
            join chunk_embeddings c
              on c.source_ref = r.source_ref
             and c.chunk_index = {unit_index_expr}
            where r.status = 'current'
            """
        ).fetchone()[0]
        or 0
    )
    return _embedding_coverage_metrics(total=total, embedded=embedded)


def embedding_coverage_metrics_connection(connection, table_names: set[str]) -> list[Metric]:
    retrieval_columns = {
        column["name"] for column in inspect(connection).get_columns("retrieval_records")
    }
    unit_index_expr = "r.unit_index" if "unit_index" in retrieval_columns else "0"
    total = float(
        connection.execute(
            text("select count(*) from retrieval_records where status = 'current'")
        ).scalar_one()
        or 0
    )
    if "chunk_embeddings" not in table_names:
        return _embedding_coverage_metrics(total=total, embedded=0.0)

    embedded = float(
        connection.execute(
            text(
                f"""
                select count(*)
                from retrieval_records r
                join chunk_embeddings c
                  on c.source_ref = r.source_ref
                 and c.chunk_index = {unit_index_expr}
                where r.status = 'current'
                """
            )
        ).scalar_one()
        or 0
    )
    return _embedding_coverage_metrics(total=total, embedded=embedded)


def retrieval_query_event_metrics_sqlite(connection: sqlite3.Connection) -> list[Metric]:
    rows = connection.execute(
        """
        select
          status,
          retriever_set,
          count(*) as request_count,
          sum(case when returned_results = 0 then 1 else 0 end) as zero_count,
          sum(pre_rerank_candidates) as pre_rerank_sum,
          sum(keyword_candidates) as keyword_sum,
          sum(vector_candidates) as vector_sum,
          sum(distinct_sources) as distinct_sources_sum,
          sum(returned_results) as returned_results_sum,
          sum(duration_ms) as duration_ms_sum
        from retrieval_query_events
        group by status, retriever_set
        """
    )
    return _retrieval_query_event_metrics_from_rows(rows)


def retrieval_query_event_metrics_connection(connection) -> list[Metric]:
    rows = connection.execute(
        text(
            """
            select
              status,
              retriever_set,
              count(*) as request_count,
              sum(case when returned_results = 0 then 1 else 0 end) as zero_count,
              sum(pre_rerank_candidates) as pre_rerank_sum,
              sum(keyword_candidates) as keyword_sum,
              sum(vector_candidates) as vector_sum,
              sum(distinct_sources) as distinct_sources_sum,
              sum(returned_results) as returned_results_sum,
              sum(duration_ms) as duration_ms_sum
            from retrieval_query_events
            group by status, retriever_set
            """
        )
    ).mappings()
    return _retrieval_query_event_metrics_from_rows(rows)


def _embedding_coverage_metrics(*, total: float, embedded: float) -> list[Metric]:
    missing = max(total - embedded, 0.0)
    coverage_ratio = 1.0 if total == 0 else embedded / total
    return [
        ("gcb_embedding_records_total", {"status": "embedded"}, embedded),
        ("gcb_embedding_records_total", {"status": "missing"}, missing),
        ("gcb_embedding_coverage_ratio", {}, coverage_ratio),
    ]


def _retrieval_query_event_metrics_from_rows(rows) -> list[Metric]:
    metrics: list[Metric] = []
    for row in rows:
        labels = {
            "retriever_set": str(row["retriever_set"]),
            "status": str(row["status"]),
        }
        request_count = float(row["request_count"] or 0)
        metrics.append(("gcb_retrieval_requests_total", labels, request_count))
        metrics.append(
            (
                "gcb_retrieval_duration_ms_sum",
                labels,
                float(row["duration_ms_sum"] or 0),
            )
        )
        retriever_labels = {"retriever_set": str(row["retriever_set"])}
        zero_count = float(row["zero_count"] or 0)
        if zero_count:
            metrics.append(
                (
                    "gcb_retrieval_zero_result_requests_total",
                    retriever_labels,
                    zero_count,
                )
            )
        for metric_name, row_key in [
            ("gcb_retrieval_pre_rerank_candidates_sum", "pre_rerank_sum"),
            ("gcb_retrieval_keyword_candidates_sum", "keyword_sum"),
            ("gcb_retrieval_vector_candidates_sum", "vector_sum"),
            ("gcb_retrieval_distinct_sources_sum", "distinct_sources_sum"),
            ("gcb_retrieval_returned_results_sum", "returned_results_sum"),
        ]:
            metrics.append((metric_name, retriever_labels, float(row[row_key] or 0)))
    return metrics


def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?", (table_name,)
    ).fetchone()
    return row is not None


def _sqlite_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"pragma table_info({table_name})")}
