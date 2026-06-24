from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

DEFAULT_MAX_LINES = 800


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail when Python files exceed a line limit.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()

    paths = staged_python_files() if args.staged else args.paths
    violations = oversized_python_files(paths, max_lines=args.max_lines)
    if violations:
        for path, line_count in violations:
            print(f"{path}: {line_count} lines exceeds {args.max_lines}")
        raise SystemExit(1)


def staged_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.endswith(".py")]


def oversized_python_files(paths: list[Path], *, max_lines: int) -> list[tuple[Path, int]]:
    violations = []
    for path in paths:
        if path.suffix != ".py" or not path.exists():
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            violations.append((path, line_count))
    return violations


if __name__ == "__main__":
    main()
