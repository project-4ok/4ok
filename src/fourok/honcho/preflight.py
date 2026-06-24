from __future__ import annotations

from collections.abc import Callable, Mapping

from fourok.honcho.sources import SourceClientError, collect_source_snapshot

REQUIRED_SOURCE_SECRETS = ("LINEAR_API_KEY", "TWENTY_API_KEY", "SLACK_BOT_TOKEN")
SourceCollector = Callable[..., dict[str, list[dict[str, object]]]]


def source_secret_preflight(secrets: Mapping[str, str]) -> dict[str, object]:
    available = {
        key: bool(value) for key in REQUIRED_SOURCE_SECRETS for value in [secrets.get(key, "")]
    }
    missing = [key for key, is_available in available.items() if not is_available]
    return {
        "status": "ok" if not missing else "missing",
        "required": list(REQUIRED_SOURCE_SECRETS),
        "available": available,
        "missing": missing,
    }


def source_connection_preflight(
    secrets: Mapping[str, str],
    *,
    sources: set[str],
    collect_snapshot: SourceCollector = collect_source_snapshot,
) -> dict[str, object]:
    source_reports: dict[str, dict[str, str]] = {}
    for source in sorted(sources):
        try:
            collect_snapshot(dict(secrets), limit=1, sources={source})
        except (RuntimeError, SourceClientError) as exc:
            source_reports[source] = {"status": "failed", "error": str(exc)}
        else:
            source_reports[source] = {"status": "ok"}
    status = (
        "ok" if all(report["status"] == "ok" for report in source_reports.values()) else "failed"
    )
    return {
        "status": status,
        "sources": source_reports,
    }
