#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = "".join(["g", "c", "b"])
LEGACY_UPPER = LEGACY.upper()
NEW_MODULE = "fourok"
NEW_PRODUCT = "4OK"
SKIP_DIRS = {
    ".git",
    ".venv",
    ".local",
    ".reference",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}
TEXT_SUFFIXES = {
    "",
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
LOWER_WORD = re.compile(rf"\b{LEGACY}\b")


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    return any(part in SKIP_DIRS for part in rel.parts)


def is_text_candidate(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name.endswith("Dockerfile")


def replace_text(text: str) -> str:
    replacements = [
        (f"{LEGACY_UPPER}_DATABASE_URL", "FOUR_OK_DATABASE_URL"),
        (f"{LEGACY_UPPER}_CONFIG_PATH", "FOUR_OK_CONFIG_PATH"),
        (f"{LEGACY_UPPER}_", "FOUR_OK_"),
        (LEGACY_UPPER, NEW_PRODUCT),
        (f"{LEGACY}_", f"{NEW_MODULE}_"),
        (f"_{LEGACY}", f"_{NEW_MODULE}"),
        (f"{LEGACY}-", f"{NEW_MODULE}-"),
        (f"-{LEGACY}", f"-{NEW_MODULE}"),
        (f"{LEGACY}.", f"{NEW_MODULE}."),
        (f".{LEGACY}", f".{NEW_MODULE}"),
        (f"/{LEGACY}", f"/{NEW_MODULE}"),
        (f"{LEGACY}/", f"{NEW_MODULE}/"),
    ]
    updated = text
    for old, new in replacements:
        updated = updated.replace(old, new)
    return LOWER_WORD.sub(NEW_MODULE, updated)


def rewrite_files() -> int:
    changed = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or should_skip(path) or not is_text_candidate(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = replace_text(text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def renamed_path(path: Path) -> Path:
    return Path(*(part.replace(LEGACY, NEW_MODULE).replace(LEGACY_UPPER, NEW_PRODUCT) for part in path.parts))


def merge_or_rename(path: Path, target: Path) -> int:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        return 1
    if path.is_dir() and target.is_dir():
        changed = 0
        for child in sorted(path.iterdir(), key=lambda p: len(p.parts), reverse=True):
            changed += merge_or_rename(child, target / child.name)
        try:
            path.rmdir()
            changed += 1
        except OSError:
            pass
        return changed
    if path.is_file() and target.is_file() and path.read_bytes() == target.read_bytes():
        path.unlink()
        return 1
    raise FileExistsError(f"cannot rename {path} -> {target}: target exists")


def rename_paths() -> int:
    changed = 0
    candidates = [path for path in ROOT.rglob("*") if not should_skip(path)]
    for path in sorted(candidates, key=lambda p: len(p.parts), reverse=True):
        target = renamed_path(path)
        if target == path or not path.exists():
            continue
        changed += merge_or_rename(path, target)
    return changed


def remove_openclaw_plugin() -> bool:
    removed = False
    plugins = ROOT / "plugins"
    if not plugins.exists():
        return False
    for path in plugins.glob("openclaw-*"):
        if path.is_dir():
            shutil.rmtree(path)
            removed = True
    return removed


def main() -> None:
    removed = remove_openclaw_plugin()
    file_changes = rewrite_files()
    path_changes = rename_paths()
    file_changes += rewrite_files()
    print(
        {
            "files_rewritten": file_changes,
            "paths_renamed": path_changes,
            "openclaw_plugin_removed": removed,
        }
    )


if __name__ == "__main__":
    main()
