from __future__ import annotations

import tarfile
from pathlib import Path

from fourok.devtools.dev import build_plan
from fourok.devtools.openclaw_skill import (
    build_openclaw_skill_archive,
    validate_openclaw_skill_package,
)


def test_validate_openclaw_skill_package_reports_publishable_cli_skill() -> None:
    report = validate_openclaw_skill_package()

    assert report["status"] == "ok"
    assert report["package_path"] == "src/fourok/retrieval/clients/openclaw"
    assert report["manifest"]["transport"] == "cli"
    assert report["manifest"]["capabilities"] == ["retrieve", "open", "status", "onboard"]
    assert report["checks"] == [
        {"name": "required_files", "status": "ok"},
        {"name": "manifest_schema", "status": "ok"},
        {"name": "client_capabilities", "status": "ok"},
        {"name": "client_only_scope", "status": "ok"},
    ]


def test_build_openclaw_skill_archive_contains_only_client_assets(tmp_path: Path) -> None:
    archive_path = build_openclaw_skill_archive(output_dir=tmp_path)

    assert archive_path == tmp_path / "openclaw-skill-fourok-retrieval.tar.gz"
    assert archive_path.exists()
    with tarfile.open(archive_path, "r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers())

    assert names == [
        "fourok-retrieval/README.md",
        "fourok-retrieval/SKILL.md",
        "fourok-retrieval/instructions.md",
        "fourok-retrieval/openclaw-skill.json",
    ]
    assert all("docker" not in name.casefold() for name in names)


def test_openclaw_skill_dev_commands_are_release_steps() -> None:
    validate_plan = build_plan("validate-openclaw-skill", [])
    archive_plan = build_plan("build-openclaw-skill", [])

    assert validate_plan[0].command == (
        "uv",
        "run",
        "python",
        "-m",
        "fourok.devtools.openclaw_skill",
        "validate",
    )
    assert archive_plan[0].command == (
        "uv",
        "run",
        "python",
        "-m",
        "fourok.devtools.openclaw_skill",
        "build",
    )
