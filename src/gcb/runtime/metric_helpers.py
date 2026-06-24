from __future__ import annotations

Metric = tuple[str, dict[str, str], float]


def source_latest_record_timestamp_metric(
    timestamp_seconds: float, source_system: object
) -> Metric:
    return (
        "gcb_source_latest_record_timestamp_seconds",
        {"source_system": str(source_system)},
        timestamp_seconds,
    )
