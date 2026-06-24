from pathlib import Path


def test_internal_prod_systemd_templates_run_compose_app_commands() -> None:
    import_service = Path("deploy/systemd/fourok-run-imports.service").read_text(encoding="utf-8")
    import_timer = Path("deploy/systemd/fourok-run-imports.timer").read_text(encoding="utf-8")
    retry_service = Path("deploy/systemd/fourok-retry-imports.service").read_text(encoding="utf-8")
    retry_timer = Path("deploy/systemd/fourok-retry-imports.timer").read_text(encoding="utf-8")
    backup_service = Path("deploy/systemd/fourok-postgres-backup.service").read_text(
        encoding="utf-8"
    )
    backup_timer = Path("deploy/systemd/fourok-postgres-backup.timer").read_text(encoding="utf-8")
    retention_service = Path("deploy/systemd/fourok-retention.service").read_text(encoding="utf-8")
    retention_timer = Path("deploy/systemd/fourok-retention.timer").read_text(encoding="utf-8")

    assert "docker compose run --rm app run-imports" in import_service
    assert "--connector gmail-singer" in import_service
    assert "--connector context-fixture" not in import_service
    assert "--config /etc/fourok/fourok.toml" in import_service
    assert "FOUROK_IMAGE_TAG=" in import_service
    assert "EnvironmentFile=/etc/fourok/fourok.env" in import_service
    assert "fourok_dev_password" not in import_service
    assert "OnUnitActiveSec=30min" in import_timer

    assert "docker compose run --rm app run-imports" in retry_service
    assert "--connector gmail-singer" in retry_service
    assert "--connector context-fixture" not in retry_service
    assert "--retry-failed" in retry_service
    assert "--retry-base-delay-seconds 300" in retry_service
    assert "EnvironmentFile=/etc/fourok/fourok.env" in retry_service
    assert "fourok_dev_password" not in retry_service
    assert "OnUnitActiveSec=10min" in retry_timer

    assert "docker compose run --rm app postgres-backup" in backup_service
    assert '--output "/var/lib/fourok/backups/fourok-' in backup_service
    assert "date +%%Y%%m%%d-%%H%%M%%S" in backup_service
    assert "EnvironmentFile=/etc/fourok/fourok.env" in backup_service
    assert "fourok_dev_password" not in backup_service
    assert "OnCalendar=*-*-* 02:15:00" in backup_timer
    assert "Persistent=true" in backup_timer

    assert "purge-raw-retention" in retention_service
    assert "purge-audit-retention" in retention_service
    assert "purge-webhook-retention" in retention_service
    assert "purge-backup-retention" in retention_service
    assert "EnvironmentFile=/etc/fourok/fourok.env" in retention_service
    assert "fourok_dev_password" not in retention_service
    assert "OnCalendar=*-*-* 03:15:00" in retention_timer
    assert "Persistent=true" in retention_timer

    env_example = Path("deploy/systemd/fourok.env.example").read_text(encoding="utf-8")
    assert (
        "FOUROK_DATABASE_URL=postgresql+psycopg://fourok:replace-with-password@postgres:5432/fourok"
        in env_example
    )
    assert "POSTGRES_PASSWORD=replace-with-postgres-password" in env_example
