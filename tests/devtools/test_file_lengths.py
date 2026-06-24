import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "check_file_lengths.py"
SPEC = importlib.util.spec_from_file_location("check_file_lengths", SCRIPT_PATH)
assert SPEC is not None
check_file_lengths = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check_file_lengths)

oversized_python_files = check_file_lengths.oversized_python_files


def test_oversized_python_files_reports_files_over_limit(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.py"
    oversized.write_text("\n".join(["x = 1"] * 3), encoding="utf-8")
    allowed = tmp_path / "allowed.py"
    allowed.write_text("\n".join(["x = 1"] * 2), encoding="utf-8")
    ignored = tmp_path / "notes.md"
    ignored.write_text("\n".join(["x"] * 5), encoding="utf-8")

    assert oversized_python_files(
        [oversized, allowed, ignored],
        max_lines=2,
    ) == [(oversized, 3)]
