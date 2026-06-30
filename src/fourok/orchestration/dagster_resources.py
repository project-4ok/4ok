from __future__ import annotations

import os
from pathlib import Path

from dagster import ConfigurableResource

from fourok.secrets.env import load_dotenv


class RawLandingResource(ConfigurableResource):
    path: str

    @property
    def root(self) -> Path:
        return Path(self.path)


class MeltanoProjectResource(ConfigurableResource):
    project_root: str

    @property
    def root(self) -> Path:
        return Path(self.project_root)


class FourokRuntimeResource(ConfigurableResource):
    state_path: str
    database_url: str

    @property
    def state(self) -> Path:
        return Path(self.state_path)


class ConnectorEnvResource(ConfigurableResource):
    dotenv_path: str = ".env"
    load_dotenv: bool = True

    def secret_env(self) -> dict[str, str]:
        if not self.load_dotenv:
            return _non_empty_env(os.environ)
        env = _non_empty_env(load_dotenv(self.dotenv_path))
        env.update(_non_empty_env(os.environ))
        return env


def _non_empty_env(env) -> dict[str, str]:
    return {key: value for key, value in env.items() if value}


def build_default_resources() -> dict[str, ConfigurableResource]:
    return {
        "raw_landing": RawLandingResource(
            path=os.environ.get("FOUROK_RAW_LANDING_DIR", ".local/raw/singer")
        ),
        "meltano_project": MeltanoProjectResource(
            project_root=os.environ.get("FOUROK_PROJECT_ROOT", ".")
        ),
        "fourok_runtime": FourokRuntimeResource(
            state_path=os.environ.get("FOUROK_STATE_PATH", ".local/dagster/fourok-state.sqlite"),
            database_url=os.environ.get("FOUROK_DATABASE_URL", ""),
        ),
        "connector_env": ConnectorEnvResource(
            dotenv_path=os.environ.get("FOUROK_DOTENV_PATH", ".env"),
            load_dotenv=_truthy(os.environ.get("FOUROK_LOAD_DOTENV", "true")),
        ),
    }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
