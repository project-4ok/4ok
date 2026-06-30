from __future__ import annotations

import importlib.resources

RECOMMENDED_MCP_TOOLS = (
    "fourok.retrieve",
    "fourok.open",
    "fourok.status",
    "fourok.onboard",
)


def retrieval_skill_md() -> str:
    return importlib.resources.files("fourok.retrieval").joinpath("SKILL.md").read_text(
        encoding="utf-8"
    )


def mcp_agent_instructions() -> str:
    return (
        importlib.resources.files("fourok.retrieval.clients.mcp")
        .joinpath("instructions.md")
        .read_text(encoding="utf-8")
    )


def skill_manifest() -> dict[str, object]:
    return {
        "name": "fourok-retrieval",
        "skill_md": retrieval_skill_md(),
        "mcp_instructions": mcp_agent_instructions(),
        "recommended_tools": list(RECOMMENDED_MCP_TOOLS),
    }
