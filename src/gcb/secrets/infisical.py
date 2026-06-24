from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from infisical_sdk import InfisicalSDKClient

DEFAULT_INFISICAL_HOST = "https://app.infisical.com"


class InfisicalClientFactory(Protocol):
    def __call__(
        self,
        *,
        host: str,
        token: str | None = None,
        cache_ttl: int = 60,
    ) -> object: ...


class SecretProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class InfisicalConfig:
    project_id: str
    environment: str = "dev"
    path: str = "/"
    domain: str = ""


def fetch_infisical_secrets(
    config: InfisicalConfig,
    *,
    client_factory: InfisicalClientFactory = InfisicalSDKClient,
    allow_cli_fallback: bool = False,
    cli_runner=subprocess.run,
) -> dict[str, str]:
    if not config.project_id:
        raise SecretProviderError("Infisical project_id is required")

    host = _infisical_host(config.domain)
    token = os.environ.get("INFISICAL_TOKEN")
    client = None
    try:
        client = client_factory(host=host, token=token, cache_ttl=60)
        if not token:
            _login_infisical(client)
        response = client.secrets.list_secrets(
            environment_slug=config.environment,
            secret_path=config.path,
            project_id=config.project_id,
        )
        return {
            secret.secretKey: secret.secretValue
            for secret in response.secrets
            if getattr(secret, "secretKey", "")
        }
    except SecretProviderError:
        if allow_cli_fallback:
            return fetch_infisical_secrets_with_cli(config, cli_runner=cli_runner)
        raise
    except Exception as error:
        raise SecretProviderError(f"Infisical SDK request failed: {_tail(str(error))}") from error
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()


def fetch_infisical_secrets_with_cli(
    config: InfisicalConfig,
    *,
    cli_runner=subprocess.run,
) -> dict[str, str]:
    command = [
        "infisical",
        "export",
        "--format",
        "json",
        "--env",
        config.environment,
        "--path",
        config.path,
        "--projectId",
        config.project_id,
        "--silent",
    ]
    if config.domain:
        command.extend(["--domain", config.domain])
    completed = cli_runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise SecretProviderError(
            f"Infisical CLI export failed with exit code {completed.returncode}"
        )
    try:
        return parse_json_export(completed.stdout)
    except ValueError as exc:
        raise SecretProviderError(f"Infisical CLI export parse failed: {exc}") from exc


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


def _login_infisical(client: object) -> None:
    client_id = os.environ.get("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID") or os.environ.get(
        "INFISICAL_CLIENT_ID"
    )
    client_secret = os.environ.get("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET") or os.environ.get(
        "INFISICAL_CLIENT_SECRET"
    )
    if not client_id:
        raise SecretProviderError(
            "Infisical auth requires INFISICAL_TOKEN or universal auth env vars"
        )
    if not client_secret:
        raise SecretProviderError(
            "Infisical auth requires INFISICAL_TOKEN or universal auth env vars"
        )

    client.auth.universal_auth.login(
        client_id=client_id,
        client_secret=client_secret,
    )


def _infisical_host(domain: str) -> str:
    host = domain or os.environ.get("INFISICAL_API_URL") or DEFAULT_INFISICAL_HOST
    normalized = host.rstrip("/")
    if normalized.endswith("/api"):
        return normalized.removesuffix("/api")
    return normalized


def _tail(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]
