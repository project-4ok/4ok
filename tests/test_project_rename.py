from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    ".local",
    ".reference",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
TEXT_SUFFIXES = {
    ".Dockerfile",
    ".cfg",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".json",
    ".lock",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
LEGACY_LOWER = "".join(("g", "c", "b"))
LEGACY_UPPER = LEGACY_LOWER.upper()


def _is_text_candidate(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
        return False
    if path.name == "test_project_rename.py":
        return False
    return path.suffix in TEXT_SUFFIXES or path.name.endswith("Dockerfile")


def test_project_text_no_longer_mentions_legacy_fourok_name() -> None:
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or not _is_text_candidate(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY_LOWER in text or LEGACY_UPPER in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
