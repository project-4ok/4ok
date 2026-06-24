from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = ROOT / "src/fourok/retrieval/SKILL.md"


def test_retrieval_agent_skill_is_valid_and_cli_first() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert skill.startswith("---\n")
    frontmatter_text, body = skill[4:].split("\n---\n", 1)
    frontmatter = yaml.safe_load(frontmatter_text)
    assert frontmatter["name"] == "fourok-retrieval"
    assert frontmatter["description"].startswith("Use when")
    assert len(frontmatter["description"]) <= 1024
    assert "uv run fourok retrieve \"<query>\" --format json" in body
    assert "uv run fourok operator-status --format json" in body
    assert "search_fourok" in body
    assert "source_ref" in body
    assert "audit_ref" in body
    assert re.search(r"Prefer MCP.*?otherwise use CLI", body, re.DOTALL)


def test_retrieval_agent_skill_is_plain_repo_artifact_not_cli_surface() -> None:
    parser_text = (ROOT / "src/fourok/cli_parts/parser_search.py").read_text(
        encoding="utf-8"
    )
    active_surface_text = (ROOT / "src/fourok/runtime/active_surface.py").read_text(
        encoding="utf-8"
    )

    assert SKILL_PATH.exists()
    assert "retrieval-skill" not in parser_text
    assert "retrieval-skill" not in active_surface_text
