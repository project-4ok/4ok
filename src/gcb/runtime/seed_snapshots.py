from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from gcb.etl.extract.context_snapshot import load_context_snapshot_source_records


def prepare_context_seed_snapshot(
    *,
    input_path: Path,
    output_path: Path,
    project_root: Path = Path("."),
) -> dict[str, object]:
    _require_local_output(output_path=output_path, project_root=project_root)

    data = _load_json_object(input_path)
    records = load_context_snapshot_source_records(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    output_path.write_bytes(encoded)

    manifest_path = output_path.with_suffix(".manifest.json")
    report = {
        "status": "ok",
        "input": str(input_path),
        "output": str(output_path),
        "manifest": str(manifest_path),
        "checksum": hashlib.sha256(encoded).hexdigest(),
        "record_count": len(records),
        "source_system_counts": dict(
            sorted(Counter(record.source_system for record in records).items())
        ),
        "record_type_counts": dict(
            sorted(Counter(record.record_type for record in records).items())
        ),
    }
    manifest_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("seed snapshot input must contain a JSON object")
    return data


def _require_local_output(*, output_path: Path, project_root: Path) -> None:
    local_root = (project_root / ".local").resolve()
    resolved_output = output_path.resolve()
    try:
        resolved_output.relative_to(local_root)
    except ValueError as exc:
        raise ValueError("seed snapshot output must be under .local") from exc
