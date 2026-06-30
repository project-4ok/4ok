from pathlib import Path

from fourok.devtools.goal_audit import audit_goal_alignment
from fourok.runtime.active_surface import ACTIVE_CLI_COMMANDS, HIDDEN_EXPERIMENT_COMMANDS


def test_goal_alignment_audit_passes_current_repo() -> None:
    report = audit_goal_alignment(Path("."))

    assert report["status"] == "ok"
    assert report["summary"]["failed"] == 0
    assert {check["name"] for check in report["checks"]} == {
        "plan_active_queue",
        "plan_proof_commands_use_active_cli",
        "plan_pytest_node_proofs_exist",
        "goal_backlog_has_open_items_for_active_plan",
        "active_docs_exclude_memory_experiments",
        "active_docs_exclude_reveal_surface",
        "cli_active_surface",
        "active_imports_exclude_deferred_modules",
        "compose_pinned_images",
        "compose_app_requires_database_url",
        "systemd_env_file_runtime_secrets",
        "alert_guidance_fields",
    }


def test_goal_alignment_audit_skips_when_goal_and_plan_missing(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "docs/goal.md").unlink()
    (tmp_path / "docs/plan.md").unlink()

    report = audit_goal_alignment(tmp_path)
    failed = [check["name"] for check in report["checks"] if check["status"] != "ok"]

    assert report["status"] == "ok"
    assert not failed


def test_goal_alignment_audit_catches_missing_plan_active_queue(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "docs/plan.md").write_text("# Plan\n", encoding="utf-8")

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert report["status"] == "failed"
    assert failed["plan_active_queue"]["reason"] == "missing active work queue"


def test_goal_alignment_audit_catches_unknown_fourok_proof_command(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "docs/plan.md").write_text(
        "## Active Work Queue\n\n1. Prove next slice.\n"
        + "\n".join(f"Proof: {index}" for index in range(8))
        + "\nProof: `uv run fourok missing-command`\n"
        + "\n## Near-Term Non-Goals\n",
        encoding="utf-8",
    )

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert report["status"] == "failed"
    assert failed["plan_proof_commands_use_active_cli"]["reason"] == (
        "unknown active proof commands: missing-command"
    )


def test_goal_alignment_audit_catches_missing_pytest_node_proof(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_cli.py").write_text(
        "def test_existing_node():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/plan.md").write_text(
        "## Active Work Queue\n\n1. Prove next slice.\n"
        + "\n".join(f"Proof: {index}" for index in range(8))
        + "\nProof: `uv run pytest tests/test_cli.py::test_missing_node -q`\n"
        + "\n## Near-Term Non-Goals\n",
        encoding="utf-8",
    )

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert report["status"] == "failed"
    assert failed["plan_pytest_node_proofs_exist"]["reason"] == (
        "missing pytest nodes: tests/test_cli.py::test_missing_node"
    )


def test_goal_alignment_audit_catches_completed_goal_with_active_plan_queue(
    tmp_path: Path,
) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "docs/goal.md").write_text(
        "# Goal Backlog\n\n- [x] Already proved.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/plan.md").write_text(
        "## Active Work Queue\n\n"
        "1. Finish active runtime cleanup.\n"
        "   Proof: `uv run fourok goal-audit`\n\n"
        "## Near-Term Non-Goals\n",
        encoding="utf-8",
    )

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert report["status"] == "failed"
    assert failed["goal_backlog_has_open_items_for_active_plan"]["reason"] == (
        "docs/plan.md has active queue items but docs/goal.md has no open checkboxes"
    )


def test_goal_alignment_audit_allows_imports_with_no_deferred_module_list(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "src/fourok/cli.py").write_text(
        "from legacy.experimental.surface import DeferredFeature\n"
        'subparsers.add_parser("search", help="active")\n',
        encoding="utf-8",
    )

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert "active_imports_exclude_deferred_modules" not in failed


def test_goal_alignment_audit_catches_systemd_embedded_runtime_password(
    tmp_path: Path,
) -> None:
    _write_minimal_repo(tmp_path)
    service_path = tmp_path / "deploy/systemd/fourok-run-imports.service"
    service_path.write_text(
        "Environment=FOUROK_DATABASE_URL=postgresql+psycopg://fourok:fourok_dev_password@postgres/fourok\n",
        encoding="utf-8",
    )

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert report["status"] == "failed"
    assert failed["systemd_env_file_runtime_secrets"]["reason"] == (
        "missing EnvironmentFile: deploy/systemd/fourok-run-imports.service; "
        "embedded dev password: deploy/systemd/fourok-run-imports.service"
    )


def test_goal_alignment_audit_catches_compose_app_database_url_default(
    tmp_path: Path,
) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  postgres:",
                "    environment:",
                "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}",
                "  app:",
                "    image: fourok-app:${FOUROK_IMAGE_TAG:?set FOUROK_IMAGE_TAG}",
                "    environment:",
                "      FOUROK_DATABASE_URL: postgresql+psycopg://fourok:fourok_dev_password@postgres:5432/fourok",
            ]
        ),
        encoding="utf-8",
    )

    report = audit_goal_alignment(tmp_path)

    failed = {check["name"]: check for check in report["checks"] if check["status"] != "ok"}
    assert report["status"] == "failed"
    assert failed["compose_app_requires_database_url"]["reason"] == (
        "app service must require explicit FOUROK_DATABASE_URL"
    )


def _write_minimal_repo(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "deploy/systemd").mkdir(parents=True)
    (root / "src/fourok/runtime").mkdir(parents=True)
    (root / "src/fourok").mkdir(parents=True, exist_ok=True)
    for relative_path in [
        "README.md",
        "docs/architecture.md",
        "docs/architecture-flow.md",
        "docs/goal.md",
        "docs/internal-prod.md",
        "docs/operations.md",
    ]:
        (root / relative_path).write_text("active runtime docs\n", encoding="utf-8")
    (root / "docs/plan.md").write_text(
        "## Active Work Queue\n\n1. Prove next slice.\n\n## Near-Term Non-Goals\n",
        encoding="utf-8",
    )
    (root / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  postgres:",
                "    environment:",
                "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}",
                "  app:",
                "    image: fourok-app:${FOUROK_IMAGE_TAG:?set FOUROK_IMAGE_TAG}",
                "    environment:",
                "      FOUROK_DATABASE_URL: ${FOUROK_DATABASE_URL:?set FOUROK_DATABASE_URL}",
            ]
        ),
        encoding="utf-8",
    )
    (root / "src/fourok/runtime/dashboard.py").write_text(
        '"threshold"\n"next_step"\n',
        encoding="utf-8",
    )
    (root / "src/fourok/runtime/acceptance.py").write_text(
        '"threshold"\n"next_step"\n',
        encoding="utf-8",
    )
    (root / "src/fourok/cli.py").write_text(
        "\n".join(
            [
                *[
                    f'subparsers.add_parser("{command}", help="active")'
                    for command in sorted(ACTIVE_CLI_COMMANDS)
                ],
                *[
                    f'subparsers.add_parser("{command}", help=argparse.SUPPRESS)\n'
                    f'_hide_subparser(subparsers, "{command}")'
                    for command in sorted(HIDDEN_EXPERIMENT_COMMANDS)
                ],
            ]
        ),
        encoding="utf-8",
    )
    (root / "deploy/systemd/fourok-run-imports.service").write_text(
        "EnvironmentFile=/etc/fourok/fourok.env\n",
        encoding="utf-8",
    )
