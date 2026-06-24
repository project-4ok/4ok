from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from fourok.runtime.active_surface import (
    ACTIVE_CLI_COMMANDS,
    DEFERRED_MODULE_PREFIXES,
    HIDDEN_EXPERIMENT_COMMANDS,
    active_import_paths,
)


@dataclass(frozen=True)
class GoalAuditCheck:
    name: str
    status: str
    reason: str = ""


ACTIVE_DOCS = (
    "README.md",
    "docs/architecture.md",
    "docs/architecture-flow.md",
    "docs/internal-prod.md",
    "docs/operations.md",
)
ACTIVE_MEMORY_DOCS = (
    "docs/architecture.md",
    "docs/architecture-flow.md",
    "docs/internal-prod.md",
    "docs/operations.md",
)
ACTIVE_RUNTIME_DOCS = (
    "README.md",
    "docs/architecture.md",
    "docs/architecture-flow.md",
    "docs/internal-prod.md",
    "docs/operations.md",
)

MEMORY_EXPERIMENT_TERMS = ("Honcho", "honcho")
ACTIVE_REVEAL_TERMS = ("request_reveal", "Search, reveal", "reveal requires")
ADD_PARSER_PATTERN = re.compile(r'add_parser\(\s*"([^"]+)"', re.DOTALL)
PLAN_FOUROK_PROOF_PATTERN = re.compile(r"Proof: `uv run fourok ([a-z0-9-]+)(?:\s|`)")
PLAN_PYTEST_NODE_PROOF_PATTERN = re.compile(
    r"Proof: `uv run pytest ([^\s`]+\.py::[A-Za-z_][A-Za-z0-9_]*)"
)
OPEN_GOAL_CHECKBOX_PATTERN = re.compile(r"^- \[ \] ", re.MULTILINE)
ACTIVE_QUEUE_ITEM_PATTERN = re.compile(r"^\d+\. ", re.MULTILINE)


def audit_goal_alignment(project_root: Path) -> dict[str, object]:
    checks = [
        _check_plan_active_queue(project_root),
        _check_plan_proof_commands_use_active_cli(project_root),
        _check_plan_pytest_node_proofs_exist(project_root),
        _check_goal_backlog_has_open_items_for_active_plan(project_root),
        _check_active_docs_exclude_memory_experiments(project_root),
        _check_active_docs_exclude_reveal_surface(project_root),
        _check_cli_active_surface(project_root),
        _check_active_imports_exclude_deferred_modules(project_root),
        _check_compose_uses_pinned_internal_images(project_root),
        _check_compose_app_requires_database_url(project_root),
        _check_systemd_uses_env_file_for_runtime_secrets(project_root),
        _check_alert_guidance_fields(project_root),
    ]
    failed = [check for check in checks if check.status != "ok"]
    return {
        "status": "ok" if not failed else "failed",
        "checks": [check.__dict__ for check in checks],
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
    }


def _check_plan_active_queue(project_root: Path) -> GoalAuditCheck:
    content = _read_optional(project_root / "docs/plan.md")
    if content is None:
        return GoalAuditCheck("plan_active_queue", "ok")
    if "## Active Work Queue" not in content:
        return GoalAuditCheck("plan_active_queue", "failed", "missing active work queue")
    if "## Current Sprint Proof Checklist" in content:
        return GoalAuditCheck(
            "plan_active_queue",
            "failed",
            "contains completed sprint proof checklist",
        )
    active_queue = content.split("## Active Work Queue", maxsplit=1)[1].split(
        "## Near-Term Non-Goals",
        maxsplit=1,
    )[0]
    if not ACTIVE_QUEUE_ITEM_PATTERN.search(active_queue):
        return GoalAuditCheck("plan_active_queue", "failed", "active work queue has no items")
    return GoalAuditCheck("plan_active_queue", "ok")


def _check_plan_proof_commands_use_active_cli(project_root: Path) -> GoalAuditCheck:
    content = _read_optional(project_root / "docs/plan.md")
    if content is None:
        return GoalAuditCheck("plan_proof_commands_use_active_cli", "ok")
    commands = PLAN_FOUROK_PROOF_PATTERN.findall(content)
    unknown = sorted({command for command in commands if command not in ACTIVE_CLI_COMMANDS})
    if unknown:
        return GoalAuditCheck(
            "plan_proof_commands_use_active_cli",
            "failed",
            f"unknown active proof commands: {', '.join(unknown)}",
        )
    return GoalAuditCheck("plan_proof_commands_use_active_cli", "ok")


def _check_plan_pytest_node_proofs_exist(project_root: Path) -> GoalAuditCheck:
    content = _read_optional(project_root / "docs/plan.md")
    if content is None:
        return GoalAuditCheck("plan_pytest_node_proofs_exist", "ok")
    missing: list[str] = []
    for node in PLAN_PYTEST_NODE_PROOF_PATTERN.findall(content):
        relative_file, test_name = node.split("::", maxsplit=1)
        path = project_root / relative_file
        if not path.exists():
            missing.append(node)
            continue
        if f"def {test_name}(" not in _read(path):
            missing.append(node)
    if missing:
        return GoalAuditCheck(
            "plan_pytest_node_proofs_exist",
            "failed",
            f"missing pytest nodes: {', '.join(missing)}",
        )
    return GoalAuditCheck("plan_pytest_node_proofs_exist", "ok")


def _check_goal_backlog_has_open_items_for_active_plan(project_root: Path) -> GoalAuditCheck:
    plan_content = _read_optional(project_root / "docs/plan.md")
    goal_content = _read_optional(project_root / "docs/goal.md")
    if plan_content is None or goal_content is None:
        return GoalAuditCheck("goal_backlog_has_open_items_for_active_plan", "ok")
    active_plan_without_open_goal = _active_queue_has_items(
        plan_content
    ) and not OPEN_GOAL_CHECKBOX_PATTERN.search(goal_content)
    if active_plan_without_open_goal:
        return GoalAuditCheck(
            "goal_backlog_has_open_items_for_active_plan",
            "failed",
            "docs/plan.md has active queue items but docs/goal.md has no open checkboxes",
        )
    return GoalAuditCheck("goal_backlog_has_open_items_for_active_plan", "ok")


def _check_active_docs_exclude_memory_experiments(project_root: Path) -> GoalAuditCheck:
    offenders = _docs_with_terms(project_root, ACTIVE_MEMORY_DOCS, MEMORY_EXPERIMENT_TERMS)
    if offenders:
        return GoalAuditCheck(
            "active_docs_exclude_memory_experiments",
            "failed",
            _format_offenders(offenders),
        )
    return GoalAuditCheck("active_docs_exclude_memory_experiments", "ok")


def _check_active_docs_exclude_reveal_surface(project_root: Path) -> GoalAuditCheck:
    offenders = _docs_with_terms(project_root, ACTIVE_RUNTIME_DOCS, ACTIVE_REVEAL_TERMS)
    if offenders:
        return GoalAuditCheck(
            "active_docs_exclude_reveal_surface",
            "failed",
            _format_offenders(offenders),
        )
    return GoalAuditCheck("active_docs_exclude_reveal_surface", "ok")


def _check_cli_active_surface(project_root: Path) -> GoalAuditCheck:
    content = _read_existing(
        project_root / "src/fourok/cli.py",
        project_root / "src/fourok/governance/cli.py",
        project_root / "src/fourok/retrieval/cli.py",
        project_root / "src/fourok/runtime/cli.py",
        project_root / "src/fourok/runtime/parser.py",
        project_root / "src/fourok/runtime/webhooks_cli.py",
        project_root / "src/fourok/storage/cli.py",
        *sorted((project_root / "src/fourok/cli_parts").glob("parser*.py")),
    )
    commands = frozenset(ADD_PARSER_PATTERN.findall(content))
    classified_commands = ACTIVE_CLI_COMMANDS | HIDDEN_EXPERIMENT_COMMANDS
    unclassified = sorted(commands - classified_commands)
    if unclassified:
        return GoalAuditCheck(
            "cli_active_surface",
            "failed",
            f"unclassified commands: {', '.join(unclassified)}",
        )
    missing_active = sorted(ACTIVE_CLI_COMMANDS - commands)
    if missing_active:
        return GoalAuditCheck(
            "cli_active_surface",
            "failed",
            f"missing active commands: {', '.join(missing_active)}",
        )
    missing = [
        command
        for command in sorted(HIDDEN_EXPERIMENT_COMMANDS)
        if command in commands and f'_hide_subparser(subparsers, "{command}")' not in content
    ]
    if missing:
        return GoalAuditCheck(
            "cli_active_surface",
            "failed",
            f"missing hidden commands: {', '.join(missing)}",
        )
    return GoalAuditCheck("cli_active_surface", "ok")


def _check_active_imports_exclude_deferred_modules(project_root: Path) -> GoalAuditCheck:
    offenders: list[str] = []
    for path in active_import_paths(project_root):
        relative_path = str(path.relative_to(project_root))
        for module_name in _imported_modules(path):
            if _is_deferred_module(module_name):
                offenders.append(f"{relative_path}: {module_name}")
    if offenders:
        return GoalAuditCheck(
            "active_imports_exclude_deferred_modules",
            "failed",
            "; ".join(offenders),
        )
    return GoalAuditCheck("active_imports_exclude_deferred_modules", "ok")


def _check_compose_uses_pinned_internal_images(project_root: Path) -> GoalAuditCheck:
    content = _read(project_root / "docker-compose.yml")
    required = (
        "fourok-app:${FOUROK_IMAGE_TAG:?set FOUROK_IMAGE_TAG}",
        "fourok-app:${FOUROK_IMAGE_TAG:-local-check}",
    )
    if not any(value in content for value in required):
        missing = [required[0]]
    else:
        missing = []
    if ":latest" in content:
        return GoalAuditCheck("compose_pinned_images", "failed", "contains :latest")
    if ".reference/" in content:
        return GoalAuditCheck("compose_pinned_images", "failed", "contains .reference path")
    if missing:
        return GoalAuditCheck(
            "compose_pinned_images",
            "failed",
            f"missing image tags: {', '.join(missing)}",
        )
    return GoalAuditCheck("compose_pinned_images", "ok")


def _check_compose_app_requires_database_url(project_root: Path) -> GoalAuditCheck:
    content = _read(project_root / "docker-compose.yml")
    app_block = _compose_service_block(content, "app")
    postgres_block = _compose_service_block(content, "postgres")
    required_database_url_values = (
        "FOUROK_DATABASE_URL: ${FOUROK_DATABASE_URL:?set FOUROK_DATABASE_URL}",
        "FOUROK_DATABASE_URL: ${FOUROK_DATABASE_URL:-postgresql+psycopg://fourok:${POSTGRES_PASSWORD:-local-check}@postgres:5432/fourok}",
    )
    required_postgres_password_values = (
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}",
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-local-check}",
    )
    if not any(value in app_block for value in required_database_url_values):
        return GoalAuditCheck(
            "compose_app_requires_database_url",
            "failed",
            "app service must require explicit FOUROK_DATABASE_URL",
        )
    if not any(value in postgres_block for value in required_postgres_password_values):
        return GoalAuditCheck(
            "compose_app_requires_database_url",
            "failed",
            "postgres service must require explicit POSTGRES_PASSWORD",
        )
    if "fourok_dev_password" in content:
        return GoalAuditCheck(
            "compose_app_requires_database_url",
            "failed",
            "compose file embeds dev database password",
        )
    return GoalAuditCheck("compose_app_requires_database_url", "ok")


def _check_systemd_uses_env_file_for_runtime_secrets(project_root: Path) -> GoalAuditCheck:
    service_paths = sorted((project_root / "deploy/systemd").glob("*.service"))
    missing_env_file = []
    embedded_passwords = []
    for path in service_paths:
        content = _read(path)
        relative_path = str(path.relative_to(project_root))
        if "EnvironmentFile=/etc/fourok/fourok.env" not in content:
            missing_env_file.append(relative_path)
        if "fourok_dev_password" in content:
            embedded_passwords.append(relative_path)
    if missing_env_file or embedded_passwords:
        parts = []
        if missing_env_file:
            parts.append(f"missing EnvironmentFile: {', '.join(missing_env_file)}")
        if embedded_passwords:
            parts.append(f"embedded dev password: {', '.join(embedded_passwords)}")
        return GoalAuditCheck(
            "systemd_env_file_runtime_secrets",
            "failed",
            "; ".join(parts),
        )
    return GoalAuditCheck("systemd_env_file_runtime_secrets", "ok")


def _check_alert_guidance_fields(project_root: Path) -> GoalAuditCheck:
    runtime_files = (
        project_root / "src/fourok/runtime/dashboard.py",
        project_root / "src/fourok/runtime/acceptance.py",
    )
    for path in runtime_files:
        content = _read(path)
        if '"threshold"' not in content or '"next_step"' not in content:
            return GoalAuditCheck(
                "alert_guidance_fields",
                "failed",
                f"missing threshold/next_step in {path.relative_to(project_root)}",
            )
    return GoalAuditCheck("alert_guidance_fields", "ok")


def _docs_with_terms(
    project_root: Path,
    paths: tuple[str, ...],
    terms: tuple[str, ...],
) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for relative_path in paths:
        content = _read(project_root / relative_path)
        found = [term for term in terms if term in content]
        if found:
            offenders[relative_path] = found
    return offenders


def _format_offenders(offenders: dict[str, list[str]]) -> str:
    return "; ".join(f"{path}: {', '.join(terms)}" for path, terms in sorted(offenders.items()))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_optional(path: Path) -> str | None:
    if not path.exists():
        return None
    return _read(path)


def _read_existing(*paths: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in paths if path.exists())


def _active_queue_has_items(content: str) -> bool:
    marker = "## Active Work Queue"
    if marker not in content:
        return False
    section = content.split(marker, maxsplit=1)[1]
    section = section.split("## Near-Term Non-Goals", maxsplit=1)[0]
    return bool(ACTIVE_QUEUE_ITEM_PATTERN.search(section))


def _compose_service_block(content: str, service_name: str) -> str:
    pattern = re.compile(rf"^  {re.escape(service_name)}:\n(?P<body>(?:    .*\n?)*)", re.MULTILINE)
    match = pattern.search(content)
    return match.group(0) if match else ""


def _imported_modules(path: Path) -> list[str]:
    if not path.exists():
        return []
    tree = ast.parse(_read(path), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def _is_deferred_module(module_name: str) -> bool:
    return any(
        module_name == deferred or module_name.startswith(f"{deferred}.")
        for deferred in DEFERRED_MODULE_PREFIXES
    )
