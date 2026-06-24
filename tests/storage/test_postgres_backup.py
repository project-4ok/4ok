from pathlib import Path

import pytest

from fourok.storage.postgres_backup import (
    BackupCommandError,
    backup_postgres,
    postgres_backup_command,
    postgres_restore_command,
    postgres_restore_drill,
    restore_postgres,
)


class FakeRunner:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.envs.append(dict(kwargs.get("env", {})))
        if command[0] == "pg_dump" and "--file" in command:
            Path(command[command.index("--file") + 1]).write_text("dump", encoding="utf-8")
        return type(
            "Completed",
            (),
            {
                "returncode": self.returncode,
                "stderr": self.stderr,
            },
        )()


def test_postgres_backup_command_uses_custom_dump_without_owner_or_acl(tmp_path: Path) -> None:
    output = tmp_path / "backups" / "fourok.dump"

    assert postgres_backup_command(
        database_url="postgresql+psycopg://fourok:secret@localhost:5432/fourok",
        output=output,
    ) == [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file",
        str(output),
        "postgresql://fourok@localhost:5432/fourok",
    ]


def test_postgres_restore_command_requires_explicit_destructive_confirmation(
    tmp_path: Path,
) -> None:
    with pytest.raises(BackupCommandError, match="--confirm-destructive-restore"):
        postgres_restore_command(
            database_url="postgresql://fourok:secret@localhost:5432/fourok_restored",
            input_path=tmp_path / "fourok.dump",
            confirm_destructive_restore=False,
        )


def test_backup_postgres_creates_output_parent_and_runs_pg_dump(tmp_path: Path) -> None:
    runner = FakeRunner()
    output = tmp_path / "nested" / "fourok.dump"

    backup_postgres(
        database_url="postgresql://fourok:secret@localhost:5432/fourok",
        output=output,
        runner=runner,
    )

    assert output.parent.exists()
    assert runner.commands[0][:2] == ["pg_dump", "--format=custom"]
    assert "secret" not in " ".join(runner.commands[0])
    assert runner.envs[0]["PGPASSWORD"] == "secret"


def test_restore_postgres_runs_pg_restore_with_clean_if_exists(tmp_path: Path) -> None:
    runner = FakeRunner()
    dump = tmp_path / "fourok.dump"
    dump.write_text("not a real dump", encoding="utf-8")

    restore_postgres(
        database_url="postgresql://fourok:secret@localhost:5432/fourok_restored",
        input_path=dump,
        confirm_destructive_restore=True,
        runner=runner,
    )

    assert runner.commands == [
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-acl",
            "--dbname",
            "postgresql://fourok@localhost:5432/fourok_restored",
            str(dump),
        ]
    ]
    assert runner.envs[0]["PGPASSWORD"] == "secret"


def test_postgres_restore_drill_rejects_source_database_as_restore_target(
    tmp_path: Path,
) -> None:
    with pytest.raises(BackupCommandError, match="must differ from source database"):
        postgres_restore_drill(
            database_url="postgresql://fourok:secret@localhost:5432/fourok",
            restore_database_url="postgresql://fourok:secret@localhost:5432/fourok",
            backup_output=tmp_path / "fourok.dump",
        )


def test_postgres_restore_drill_backs_up_restores_and_checks_restored_health(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()

    report = postgres_restore_drill(
        database_url="postgresql://fourok:secret@localhost:5432/fourok",
        restore_database_url="postgresql://fourok:restore@localhost:5432/fourok_restore_drill",
        backup_output=tmp_path / "fourok.dump",
        runner=runner,
        health_check=lambda database_url: {
            "status": "ok",
            "database_url": database_url,
            "source_record_count": 3,
        },
    )

    assert [command[0] for command in runner.commands] == ["pg_dump", "pg_restore"]
    assert "secret" not in " ".join(runner.commands[0])
    assert "restore@" not in " ".join(runner.commands[1])
    assert runner.envs[0]["PGPASSWORD"] == "secret"
    assert runner.envs[1]["PGPASSWORD"] == "restore"
    assert report == {
        "status": "completed",
        "backup": str(tmp_path / "fourok.dump"),
        "restore_database": "postgresql://fourok@localhost:5432/fourok_restore_drill",
        "health": {
            "status": "ok",
            "database_url": "postgresql://fourok:restore@localhost:5432/fourok_restore_drill",
            "source_record_count": 3,
        },
    }


def test_postgres_restore_drill_fails_when_restored_health_fails(tmp_path: Path) -> None:
    runner = FakeRunner()

    with pytest.raises(BackupCommandError, match="restore drill health check failed"):
        postgres_restore_drill(
            database_url="postgresql://fourok:secret@localhost:5432/fourok",
            restore_database_url="postgresql://fourok:restore@localhost:5432/fourok_restore_drill",
            backup_output=tmp_path / "fourok.dump",
            runner=runner,
            health_check=lambda _database_url: {"status": "failed"},
        )
