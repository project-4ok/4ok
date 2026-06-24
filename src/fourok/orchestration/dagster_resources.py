from __future__ import annotations

import os
from pathlib import Path

from dagster import ConfigurableResource

from fourok.secrets.env import effective_env


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


class 4okRuntimeResource(ConfigurableResource):
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
            return dict(os.environ)
        return effective_env(dotenv_path=self.dotenv_path)


def build_default_resources() -> dict[str, ConfigurableResource]:
    return {
        "raw_landing": RawLandingResource(
            path=os.environ.get("FOUR_OK_RAW_LANDING_DIR", ".local/raw/singer")
        ),
        "meltano_project": MeltanoProjectResource(
            project_root=os.environ.get("FOUR_OK_PROJECT_ROOT", ".")
        ),
        "fourok_runtime": 4okRuntimeResource(
            state_path=os.environ.get("FOUR_OK_STATE_PATH", ".local/dagster/fourok-state.sqlite"),
            database_url=os.environ.get("FOUR_OK_DATABASE_URL", ""),
        ),
        "connector_env": ConnectorEnvResource(
            dotenv_path=os.environ.get("FOUR_OK_DOTENV_PATH", ".env"),
            load_dotenv=_truthy(os.environ.get("FOUR_OK_LOAD_DOTENV", "true")),
        ),
    }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
