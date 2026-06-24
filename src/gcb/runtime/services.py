from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeServiceBoundary:
    name: str
    current_runtime: str
    target_runtime: str
    responsibilities: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    health_check: str = ""
    not_yet: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "current_runtime": self.current_runtime,
            "target_runtime": self.target_runtime,
            "responsibilities": list(self.responsibilities),
            "dependencies": list(self.dependencies),
            "health_check": self.health_check,
            "not_yet": list(self.not_yet),
        }


def runtime_service_boundaries() -> list[RuntimeServiceBoundary]:
    return sorted(
        [
            RuntimeServiceBoundary(
                name="context-api",
                current_runtime="CLI facade",
                target_runtime="HTTP/service API behind human session and agent identity",
                responsibilities=(
                    "search_context",
                    "permission-filtered source metadata",
                ),
                dependencies=("metadata-database", "policy-engine", "audit-store"),
                health_check="gcb health",
                not_yet=("public HTTP API", "real agent session integration"),
            ),
            RuntimeServiceBoundary(
                name="connector-runner",
                current_runtime="manual command",
                target_runtime="scheduled worker with durable state",
                responsibilities=(
                    "source sync",
                    "stored checkpoints",
                    "job run history",
                    "bounded retry/backoff",
                    "per-connector running-job guard",
                    "raw landing",
                ),
                dependencies=("secrets-provider", "metadata-database", "raw-source-store"),
                health_check="run_gmail_pilot.py --preflight",
                not_yet=("production broker decision",),
            ),
            RuntimeServiceBoundary(
                name="webhook-backlog",
                current_runtime="database-backed CLI worker",
                target_runtime="broker-neutral event intake with durable processing workers",
                responsibilities=(
                    "webhook raw landing",
                    "idempotent event backlog",
                    "source change processing",
                    "failure visibility",
                ),
                dependencies=("metadata-database", "raw-source-store"),
                health_check="gcb webhook-events",
                not_yet=("HTTP intake endpoint", "signature verification", "production broker"),
            ),
            RuntimeServiceBoundary(
                name="document-extraction-worker",
                current_runtime="Docker Compose experiment",
                target_runtime="isolated optional worker/container",
                responsibilities=(
                    "attachment parsing",
                    "OCR experiment",
                    "source attachment mapping",
                ),
                dependencies=("raw-source-store",),
                health_check="docker compose --profile experiments run --rm docling-worker",
                not_yet=("production worker image", "representative attachment benchmark"),
            ),
            RuntimeServiceBoundary(
                name="policy-engine",
                current_runtime="static source-access policy",
                target_runtime="source-permission policy decision point",
                responsibilities=("source retrieval authorization",),
                dependencies=("identity provider",),
                health_check="scripts/smoke_runtime.py",
                not_yet=(
                    "real SSO groups",
                    "source-permission policy import",
                    "PII/token reveal policy",
                ),
            ),
            RuntimeServiceBoundary(
                name="metadata-database",
                current_runtime="SQLAlchemy over SQLite or PostgreSQL",
                target_runtime="PostgreSQL",
                responsibilities=(
                    "metadata state",
                    "raw internal retrieval chunks",
                    "connector state",
                ),
                health_check="gcb health",
                not_yet=(),
            ),
            RuntimeServiceBoundary(
                name="raw-source-store",
                current_runtime="restricted local filesystem",
                target_runtime="object storage with retention and deletion propagation",
                responsibilities=("restricted raw objects", "retention purge", "source lineage"),
                health_check="gcb health",
                not_yet=("object-store backend", "raw-source encryption decision"),
            ),
            RuntimeServiceBoundary(
                name="secrets-provider",
                current_runtime="Infisical SDK in process",
                target_runtime="Infisical machine identity or runtime secret injection",
                responsibilities=("connector credentials", "redacted preflight"),
                dependencies=("Infisical",),
                health_check="run_gmail_pilot.py --preflight",
                not_yet=("policy-service secrets", "identity-service secrets"),
            ),
            RuntimeServiceBoundary(
                name="audit-store",
                current_runtime="PostgreSQL-compatible audit table",
                target_runtime="queryable audit store, PostgreSQL first and OpenSearch if needed",
                responsibilities=(
                    "access decisions",
                    "retention purge",
                    "summary counts",
                ),
                dependencies=("metadata-database",),
                health_check="gcb audit-summary",
                not_yet=("audit dashboard", "deny-rate alerting", "OpenSearch decision"),
            ),
        ],
        key=lambda boundary: boundary.name,
    )
