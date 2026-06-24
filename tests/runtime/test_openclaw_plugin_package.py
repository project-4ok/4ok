import json
from pathlib import Path

PLUGIN_DIR = Path("plugins/openclaw-fourok")


def test_openclaw_fourok_manifest_declares_local_search_and_health_tools() -> None:
    manifest = json.loads((PLUGIN_DIR / "openclaw.plugin.json").read_text())

    assert manifest["id"] == "fourok-local"
    assert "kind" not in manifest
    assert manifest["contracts"]["tools"] == ["fourok_search_context", "fourok_health"]
    assert "apiKey" not in json.dumps(manifest).casefold()
    assert manifest["configSchema"]["properties"]["command"]["default"] == "fourok"
    assert manifest["configSchema"]["properties"]["state"]["default"] == ".local/context.sqlite"
    assert manifest["configSchema"]["properties"]["rawStore"]["default"] == ".local/raw"


def test_openclaw_fourok_package_exports_manifest_and_dist_entry() -> None:
    package = json.loads((PLUGIN_DIR / "package.json").read_text())

    assert package["name"] == "@4ok/fourok-openclaw-plugin"
    assert package["type"] == "module"
    assert package["main"] == "dist/index.js"
    assert package["openclaw"]["plugin"] == "./openclaw.plugin.json"
    assert package["openclaw"]["extensions"] == ["./dist/index.js"]
    assert set(package["files"]) == {"dist", "openclaw.plugin.json", "README.md"}


def test_openclaw_fourok_plugin_registers_only_local_fourok_tools() -> None:
    index = (PLUGIN_DIR / "src/index.ts").read_text()

    assert "definePluginEntry({" in index
    assert "api.registerTool(" in index
    assert 'name: "fourok_search_context"' in index
    assert 'name: "fourok_health"' in index
    assert '"search-state"' in index
    assert '"health"' in index
    assert "spawn(" in index
    assert "request_reveal" not in index
    assert "appendSystemContext" not in index
    assert ".reference" not in index


def test_openclaw_fourok_readme_documents_local_install_and_cli_contract() -> None:
    readme = (PLUGIN_DIR / "README.md").read_text()

    assert "fourok_search_context" in readme
    assert "fourok_health" in readme
    assert "uv run fourok search-state" in readme
    assert "uv run fourok health" in readme
    assert "does not expose reveal" in readme
