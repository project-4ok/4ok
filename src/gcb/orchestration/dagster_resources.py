from __future__ import annotations

import os
from pathlib import Path

from dagster import ConfigurableResource

from gcb.secrets.infisical import InfisicalConfig, fetch_infisical_secrets


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


class GcbRuntimeResource(ConfigurableResource):
    state_path: str
    database_url: str

    @property
    def state(self) -> Path:
        return Path(self.state_path)


class InfisicalSecretsResource(ConfigurableResource):
    project_id: str = ""
    environment: str = "runtime"
    path: str = "/"
    domain: str = ""
    enabled: bool = False

    def secret_env(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        return fetch_infisical_secrets(
            InfisicalConfig(
                project_id=self.project_id,
                environment=self.environment,
                path=self.path,
                domain=self.domain,
            )
        )


def build_default_resources() -> dict[str, ConfigurableResource]:
    return {
        "raw_landing": RawLandingResource(
            path=os.environ.get("GCB_RAW_LANDING_DIR", ".local/raw/singer")
        ),
        "meltano_project": MeltanoProjectResource(
            project_root=os.environ.get("GCB_PROJECT_ROOT", ".")
        ),
        "gcb_runtime": GcbRuntimeResource(
            state_path=os.environ.get("GCB_STATE_PATH", ".local/dagster/gcb-state.sqlite"),
            database_url=os.environ.get("GCB_DATABASE_URL", ""),
        ),
        "infisical_secrets": InfisicalSecretsResource(
            enabled=_truthy(os.environ.get("GCB_INFISICAL_ENABLED", ""))
            or bool(_env_first("GCB_INFISICAL_PROJECT_ID", "INFISICAL_PROJECT_ID")),
            project_id=_env_first("GCB_INFISICAL_PROJECT_ID", "INFISICAL_PROJECT_ID"),
            environment=_env_first("GCB_INFISICAL_ENV", "INFISICAL_ENV", default="runtime"),
            path=_env_first("GCB_INFISICAL_PATH", "INFISICAL_PATH", default="/"),
            domain=_env_first("GCB_INFISICAL_DOMAIN", "INFISICAL_DOMAIN", "INFISICAL_API_URL"),
        ),
    }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default
