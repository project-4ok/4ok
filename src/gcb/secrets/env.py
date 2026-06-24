from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

_SECRET_KEY_MARKERS = ("SECRET", "TOKEN", "API_KEY", "PASSWORD", "PRIVATE_KEY", "CREDENTIAL")


def parse_dotenv_export_lines(lines: Sequence[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").strip()
        if "=" not in stripped:
            raise ValueError(f"Invalid env line {line_number}: expected KEY=value")
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid env line {line_number}: missing key")
        try:
            value = shlex.split(raw_value, comments=False, posix=True)
        except ValueError as error:
            raise ValueError(f"Invalid env line {line_number}: {error}") from error
        if len(value) != 1:
            raise ValueError(f"Invalid env line {line_number}: expected one value")
        values[key] = value[0]
    return values


def parse_json_export(raw_json: str) -> dict[str, str]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("expected JSON object") from exc
    if isinstance(data, dict):
        return {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and isinstance(value, str)
        }
    if isinstance(data, list):
        values: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("secretKey") or item.get("name")
            value = item.get("value") or item.get("secretValue")
            if isinstance(key, str) and isinstance(value, str):
                values[key] = value
        return values
    raise ValueError("expected JSON object or list")


def load_dotenv(path: str | Path) -> dict[str, str]:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return {}
    return parse_dotenv_export_lines(dotenv_path.read_text(encoding="utf-8").splitlines())


def effective_env(
    *, dotenv_path: str | Path = ".env", base: Mapping[str, str] | None = None
) -> dict[str, str]:
    env = load_dotenv(dotenv_path)
    env.update(dict(os.environ if base is None else base))
    return env


def redacted_env_report(env: Mapping[str, str], *, keys: Sequence[str]) -> dict[str, str]:
    return {key: _redacted_value(key, env.get(key, "")) for key in keys}


def _redacted_value(key: str, value: str) -> str:
    if not value:
        return "missing"
    upper = key.upper()
    if any(marker in upper for marker in _SECRET_KEY_MARKERS):
        return "[REDACTED]"
    return value
