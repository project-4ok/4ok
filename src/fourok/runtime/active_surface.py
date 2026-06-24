from __future__ import annotations

from pathlib import Path

ACTIVE_CLI_COMMANDS = frozenset(
    {
        "acceptance-proof",
        "access-smoke",
        "ask",
        "audit",
        "audit-summary",
        "backup-state",
        "backfill-openviking-messages",
        "connector-checkpoint",
        "connector-jobs",
        "dashboard",
        "dependency-contracts",
        "eval-retrieval",
        "goal-audit",
        "health",
        "import-context-fixture",
        "internal-prod-readiness",
        "ingest-gmail-singer",
        "ingest-pdf",
        "land-singer",
        "live-ingestion-status",
        "live-retrieval-case-set",
        "observability-smoke",
        "operator-status",
        "postgres-backup",
        "postgres-restore",
        "postgres-restore-drill",
        "prepare-seed-snapshot",
        "purge-audit-retention",
        "purge-backup-retention",
        "purge-raw-retention",
        "purge-webhook-retention",
        "rebuild-retrieval-units",
        "restore-state",
        "retrieve",
        "retention-status",
        "run-imports",
        "run-live-ingestion",
        "runtime-monitor",
        "runtime-services",
        "search",
        "search-state",
        "stage1-acceptance",
        "webhook-enqueue",
        "webhook-events",
        "webhook-process",
    }
)

HIDDEN_EXPERIMENT_COMMANDS = frozenset(
    {
        "evidence-baseline-eval",
        "graphiti-episodes",
        "honcho-eval",
        "honcho-preflight",
        "honcho-receipt",
        "honcho-smoke",
        "honcho-sync",
    }
)

DEFERRED_MODULE_PREFIXES = frozenset(
    {
        "fourok.governance.deferred_reveal_policy",
        "fourok.governance.reveal",
        "fourok.governance.token_store",
        "fourok.honcho",
        "fourok.evaluation",
        "fourok.retrieval.evidence_baseline",
        "fourok.retrieval.graphiti_episodes",
        "fourok.etl.transform.pii",
        "fourok.etl.transform.tokens",
    }
)


def active_import_paths(project_root: Path) -> tuple[Path, ...]:
    source_root = project_root / "src/fourok"
    if not source_root.exists():
        return ()
    return tuple(
        sorted(
            path for path in source_root.rglob("*.py") if not _is_deferred_path(project_root, path)
        )
    )


def _is_deferred_path(project_root: Path, path: Path) -> bool:
    relative_module = path.relative_to(project_root / "src").with_suffix("")
    module_name = ".".join(relative_module.parts)
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in DEFERRED_MODULE_PREFIXES
    )
