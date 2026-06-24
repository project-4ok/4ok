import json
from pathlib import Path

PLUGIN_DIR = Path("plugins/openclaw-gcb")


def test_openclaw_gcb_manifest_declares_local_search_and_health_tools() -> None:
    manifest = json.loads((PLUGIN_DIR / "openclaw.plugin.json").read_text())

    assert manifest["id"] == "gcb-local"
    assert "kind" not in manifest
    assert manifest["contracts"]["tools"] == ["gcb_search_context", "gcb_health"]
    assert "apiKey" not in json.dumps(manifest).casefold()
    assert manifest["configSchema"]["properties"]["command"]["default"] == "gcb"
    assert manifest["configSchema"]["properties"]["state"]["default"] == ".local/context.sqlite"
    assert manifest["configSchema"]["properties"]["rawStore"]["default"] == ".local/raw"


def test_openclaw_gcb_package_exports_manifest_and_dist_entry() -> None:
    package = json.loads((PLUGIN_DIR / "package.json").read_text())

    assert package["name"] == "@4ok/gcb-openclaw-plugin"
    assert package["type"] == "module"
    assert package["main"] == "dist/index.js"
    assert package["openclaw"]["plugin"] == "./openclaw.plugin.json"
    assert package["openclaw"]["extensions"] == ["./dist/index.js"]
    assert set(package["files"]) == {"dist", "openclaw.plugin.json", "README.md"}


def test_openclaw_gcb_plugin_registers_only_local_gcb_tools() -> None:
    index = (PLUGIN_DIR / "src/index.ts").read_text()

    assert "definePluginEntry({" in index
    assert "api.registerTool(" in index
    assert 'name: "gcb_search_context"' in index
    assert 'name: "gcb_health"' in index
    assert '"search-state"' in index
    assert '"health"' in index
    assert "spawn(" in index
    assert "request_reveal" not in index
    assert "appendSystemContext" not in index
    assert ".reference" not in index


def test_openclaw_gcb_readme_documents_local_install_and_cli_contract() -> None:
    readme = (PLUGIN_DIR / "README.md").read_text()

    assert "gcb_search_context" in readme
    assert "gcb_health" in readme
    assert "uv run gcb search-state" in readme
    assert "uv run gcb health" in readme
    assert "does not expose reveal" in readme
