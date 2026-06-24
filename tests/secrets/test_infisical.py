from __future__ import annotations

from dataclasses import dataclass

import pytest

from gcb.secrets.infisical import (
    InfisicalConfig,
    SecretProviderError,
    _infisical_host,
    fetch_infisical_secrets,
    parse_dotenv_export_lines,
    parse_json_export,
)


@dataclass(frozen=True)
class FakeSecret:
    secretKey: str
    secretValue: str


@dataclass(frozen=True)
class FakeSecretList:
    secrets: list[FakeSecret]


class FakeUniversalAuth:
    def __init__(self) -> None:
        self.login_calls: list[dict[str, str]] = []

    def login(self, *, client_id: str, client_secret: str) -> None:
        self.login_calls.append({"client_id": client_id, "client_secret": client_secret})


class FakeSecrets:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, str]] = []

    def list_secrets(self, **kwargs) -> FakeSecretList:
        self.list_calls.append(kwargs)
        return FakeSecretList(
            secrets=[
                FakeSecret("TAP_GMAIL_USER_ID", "pilot@example.com"),
                FakeSecret("TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID", "client-id"),
            ]
        )


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, *, host: str, token: str | None = None, cache_ttl: int = 60) -> None:
        self.host = host
        self.token = token
        self.cache_ttl = cache_ttl
        self.auth = type("FakeAuth", (), {"universal_auth": FakeUniversalAuth()})()
        self.secrets = FakeSecrets()
        self.closed = False
        self.instances.append(self)

    def close(self) -> None:
        self.closed = True


def test_parse_dotenv_export_lines_supports_export_and_quotes() -> None:
    values = parse_dotenv_export_lines(
        [
            'export TAP_GMAIL_USER_ID="pilot@example.com"',
            "TAP_GMAIL_MESSAGES_Q='newer_than:30d GCB-PILOT'",
            "",
        ]
    )

    assert values == {
        "TAP_GMAIL_USER_ID": "pilot@example.com",
        "TAP_GMAIL_MESSAGES_Q": "newer_than:30d GCB-PILOT",
    }


def test_parse_json_export_supports_multiline_values() -> None:
    values = parse_json_export(
        '{"LINEAR_API_KEY":"linear-secret","PRIVATE_KEY":"line one\\nline two"}'
    )

    assert values == {
        "LINEAR_API_KEY": "linear-secret",
        "PRIVATE_KEY": "line one\nline two",
    }


def test_parse_json_export_supports_infisical_cli_list_shape() -> None:
    values = parse_json_export(
        '[{"key":"LINEAR_API_KEY","value":"linear-secret"},'
        '{"key":"TWENTY_API_KEY","value":"twenty-secret"}]'
    )

    assert values == {
        "LINEAR_API_KEY": "linear-secret",
        "TWENTY_API_KEY": "twenty-secret",
    }


@pytest.mark.parametrize(
    ("configured_host", "expected_host"),
    [
        ("https://infisical.internal/api", "https://infisical.internal"),
        ("https://eu.infisical.com", "https://eu.infisical.com"),
    ],
)
def test_infisical_host_normalizes_sdk_host(configured_host: str, expected_host: str) -> None:
    assert _infisical_host(configured_host) == expected_host


def test_fetch_infisical_secrets_uses_universal_auth_env_without_secret_args(monkeypatch) -> None:
    FakeClient.instances.clear()
    monkeypatch.setenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", "machine-client-id")
    monkeypatch.setenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", "machine-client-secret")

    values = fetch_infisical_secrets(
        InfisicalConfig(
            project_id="project-123",
            environment="dev",
            path="/gmail-pilot",
            domain="https://eu.infisical.com",
        ),
        client_factory=FakeClient,
    )
    client = FakeClient.instances[0]

    assert values["TAP_GMAIL_USER_ID"] == "pilot@example.com"
    assert client.host == "https://eu.infisical.com"
    assert client.auth.universal_auth.login_calls == [
        {"client_id": "machine-client-id", "client_secret": "machine-client-secret"}
    ]
    assert client.secrets.list_calls == [
        {
            "environment_slug": "dev",
            "secret_path": "/gmail-pilot",
            "project_id": "project-123",
        }
    ]
    assert client.closed is True


def test_fetch_infisical_secrets_accepts_infisical_client_aliases(monkeypatch, capsys) -> None:
    FakeClient.instances.clear()
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "machine-client-id")
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET", "machine-client-secret")

    values = fetch_infisical_secrets(
        InfisicalConfig(project_id="project-123"),
        client_factory=FakeClient,
    )
    captured = capsys.readouterr()
    client = FakeClient.instances[0]

    assert values["TAP_GMAIL_USER_ID"] == "pilot@example.com"
    assert client.auth.universal_auth.login_calls == [
        {"client_id": "machine-client-id", "client_secret": "machine-client-secret"}
    ]
    assert captured.out == ""
    assert captured.err == ""
    assert "machine-client-id" not in captured.out
    assert "machine-client-secret" not in captured.out


def test_fetch_infisical_secrets_uses_existing_token_without_login(monkeypatch) -> None:
    FakeClient.instances.clear()
    monkeypatch.setenv("INFISICAL_TOKEN", "existing-token")

    fetch_infisical_secrets(InfisicalConfig(project_id="project-123"), client_factory=FakeClient)
    client = FakeClient.instances[0]

    assert client.token == "existing-token"
    assert client.auth.universal_auth.login_calls == []


def test_fetch_infisical_secrets_requires_auth_env(monkeypatch) -> None:
    monkeypatch.delenv("INFISICAL_TOKEN", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)

    with pytest.raises(SecretProviderError, match="INFISICAL_TOKEN or universal auth env vars"):
        fetch_infisical_secrets(
            InfisicalConfig(project_id="project-123"), client_factory=FakeClient
        )


def test_fetch_infisical_secrets_can_fallback_to_logged_in_cli(monkeypatch) -> None:
    monkeypatch.delenv("INFISICAL_TOKEN", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)
    calls: list[dict[str, object]] = []

    def fake_cli_runner(command: list[str], **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": (
                    '{"LINEAR_API_KEY":"linear-secret",'
                    '"TWENTY_API_KEY":"twenty-secret",'
                    '"SLACK_BOT_TOKEN":"slack-secret"}'
                ),
                "stderr": "",
            },
        )()

    values = fetch_infisical_secrets(
        InfisicalConfig(
            project_id="project-123",
            environment="runtime",
            path="/customer-consumable/customers/4ok/runtime",
        ),
        client_factory=FakeClient,
        allow_cli_fallback=True,
        cli_runner=fake_cli_runner,
    )

    assert values == {
        "LINEAR_API_KEY": "linear-secret",
        "TWENTY_API_KEY": "twenty-secret",
        "SLACK_BOT_TOKEN": "slack-secret",
    }
    assert calls == [
        {
            "command": [
                "infisical",
                "export",
                "--format",
                "json",
                "--env",
                "runtime",
                "--path",
                "/customer-consumable/customers/4ok/runtime",
                "--projectId",
                "project-123",
                "--silent",
            ],
            "kwargs": {"capture_output": True, "text": True, "check": False},
        }
    ]


def test_fetch_infisical_cli_fallback_error_is_redacted(monkeypatch) -> None:
    monkeypatch.delenv("INFISICAL_TOKEN", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)

    def fake_cli_runner(command: list[str], **kwargs):
        return type(
            "Completed",
            (),
            {
                "returncode": 1,
                "stdout": 'LINEAR_API_KEY="linear-secret"\n',
                "stderr": "permission denied",
            },
        )()

    with pytest.raises(SecretProviderError) as exc_info:
        fetch_infisical_secrets(
            InfisicalConfig(project_id="project-123"),
            client_factory=FakeClient,
            allow_cli_fallback=True,
            cli_runner=fake_cli_runner,
        )

    assert "Infisical CLI export failed with exit code 1" in str(exc_info.value)
    assert "linear-secret" not in str(exc_info.value)
