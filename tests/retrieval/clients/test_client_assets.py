from __future__ import annotations

import importlib.resources

from fourok.retrieval.clients import cli as cli_client
from fourok.retrieval.clients import openclaw as openclaw_client
from fourok.retrieval.clients.mcp import server as mcp_server

EXPECTED_CAPABILITIES = ("retrieve", "open", "status", "onboard")


def test_cli_client_is_package_with_colocated_skill_assets() -> None:
    assert callable(cli_client.retrieve_augmentation)

    skill = importlib.resources.files("fourok.retrieval.clients.cli").joinpath("SKILL.md")
    instructions = importlib.resources.files("fourok.retrieval.clients.cli").joinpath(
        "instructions.md"
    )

    assert skill.is_file()
    assert instructions.is_file()
    assert "# fourok Retrieval" in skill.read_text(encoding="utf-8")
    assert "fourok retrieve" in instructions.read_text(encoding="utf-8")


def test_openclaw_client_assets_are_colocated_with_client_adapter() -> None:
    skill = openclaw_client.skill_markdown()
    instructions = openclaw_client.instructions_markdown()
    manifest = openclaw_client.skill_manifest()

    assert "# fourok Retrieval" in skill
    assert "fourok retrieve" in instructions
    assert manifest["name"] == "fourok-openclaw"
    assert manifest["transport"] == "cli"
    assert manifest["entrypoint"] == "SKILL.md"
    assert manifest["instructions"] == "instructions.md"
    assert manifest["capabilities"] == list(EXPECTED_CAPABILITIES)
    assert manifest["required_commands"] == ["fourok"]
    assert manifest["source_path"] == "src/fourok/retrieval/clients/openclaw"


def test_retrieval_clients_expose_same_logical_capabilities() -> None:
    assert cli_client.client_capabilities() == EXPECTED_CAPABILITIES
    assert openclaw_client.client_capabilities() == EXPECTED_CAPABILITIES
    assert tuple(tool["name"].removeprefix("fourok.") for tool in mcp_server.tool_schemas()) == (
        "retrieve",
        "open",
        "status",
        "onboard",
    )


def test_openclaw_skill_manifest_is_static_hub_metadata_not_runtime_deployment() -> None:
    manifest = openclaw_client.skill_manifest()
    serialized = str(manifest).casefold()

    assert "docker" not in serialized
    assert "dagster" not in serialized
    assert "database" not in serialized
    assert manifest["recommended_commands"] == [
        "fourok status",
        "fourok retrieve <query> --json",
        "fourok open <source_ref>",
    ]
