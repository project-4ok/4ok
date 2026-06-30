from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = ROOT / "src/fourok/retrieval/clients/cli/SKILL.md"


def test_retrieval_agent_skill_is_valid_and_cli_first() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert skill.startswith("---\n")
    frontmatter_text, body = skill[4:].split("\n---\n", 1)
    frontmatter = yaml.safe_load(frontmatter_text)
    assert frontmatter["name"] == "fourok-retrieval"
    assert frontmatter["description"].startswith("Use the fourok CLI")
    assert len(frontmatter["description"]) <= 1024
    assert 'fourok retrieve "<query>" --json' in body
    assert "fourok status" in body
    assert "fourok open <source_ref>" in body
    assert "source_ref" in body
    assert "audit_ref" in body
    assert re.search(r"source-backed.*?evidence", body, re.DOTALL)


def test_retrieval_agent_skill_is_plain_repo_artifact_not_cli_surface() -> None:
    parser_text = (ROOT / "src/fourok/retrieval/cli.py").read_text(encoding="utf-8")
    active_surface_text = (ROOT / "src/fourok/runtime/active_surface.py").read_text(
        encoding="utf-8"
    )

    assert SKILL_PATH.exists()
    assert "retrieval-skill" not in parser_text
    assert "retrieval-skill" not in active_surface_text
