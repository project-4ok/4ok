import json
from pathlib import Path

import pytest

from fourok.runtime.seed_snapshots import prepare_context_seed_snapshot

FIXTURES = Path(__file__).parents[1] / "fixtures" / "context_substrate"


def test_prepare_context_seed_snapshot_writes_ignored_seed_and_manifest(tmp_path: Path) -> None:
    output = tmp_path / ".local" / "seeds" / "context-substrate.json"

    report = prepare_context_seed_snapshot(
        input_path=FIXTURES / "source_snapshot_eval.json",
        output_path=output,
        project_root=tmp_path,
    )

    manifest = output.with_suffix(".manifest.json")
    assert output.exists()
    assert manifest.exists()
    assert report == json.loads(manifest.read_text(encoding="utf-8"))
    assert report == {
        "status": "ok",
        "input": str(FIXTURES / "source_snapshot_eval.json"),
        "output": str(output),
        "manifest": str(manifest),
        "checksum": report["checksum"],
        "record_count": 20,
        "source_system_counts": {
            "linear": 14,
            "slack": 3,
            "twenty": 3,
        },
        "record_type_counts": {
            "message": 3,
            "person": 9,
            "project": 2,
            "resource": 2,
            "work_item": 4,
        },
    }
    assert len(report["checksum"]) == 64
    assert "Robin Scharf confirmed" not in str(report)


def test_prepare_context_seed_snapshot_rejects_outputs_outside_local(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="seed snapshot output must be under .local"):
        prepare_context_seed_snapshot(
            input_path=FIXTURES / "source_snapshot_eval.json",
            output_path=tmp_path / "committed-seed.json",
            project_root=tmp_path,
        )
