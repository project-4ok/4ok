from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any

from gcb.storage.config import RawStoreConfig


class FileRawSourceStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, source_ref: str, payload: Any) -> None:
        path = self.path_for(source_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_jsonable(payload), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def delete(self, source_ref: str) -> None:
        path = self.path_for(source_ref)
        if path.exists():
            path.unlink()

    def exists(self, source_ref: str) -> bool:
        return self.path_for(source_ref).exists()

    def refs(self) -> list[str]:
        refs = []
        for path in sorted(self._root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_ref = payload.get("source_ref") if isinstance(payload, dict) else None
            if isinstance(source_ref, str):
                refs.append(source_ref)
        return refs

    def path_for(self, source_ref: str) -> Path:
        digest = blake2b(source_ref.encode(), digest_size=16, person=b"gcbrawsrc").hexdigest()
        return self._root / f"{digest}.json"


def raw_source_store_from_config(config: RawStoreConfig) -> FileRawSourceStore | None:
    if config.backend is None and config.path is None:
        return None

    backend = config.backend or "filesystem"
    if backend != "filesystem":
        raise ValueError(f"unsupported raw source store backend: {backend}")
    if config.path is None:
        raise ValueError("raw_store.path is required for filesystem raw source store")
    return FileRawSourceStore(config.path)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
