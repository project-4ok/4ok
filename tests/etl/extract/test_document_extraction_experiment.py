from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "evaluate_document_extraction.py"
REPO_ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location("evaluate_document_extraction", SCRIPT_PATH)
assert SPEC is not None
document_extraction_experiment = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = document_extraction_experiment
SPEC.loader.exec_module(document_extraction_experiment)

MARKER = document_extraction_experiment.MARKER
create_synthetic_fixtures = document_extraction_experiment.create_synthetic_fixtures
evaluate_documents = document_extraction_experiment.evaluate_documents
write_summary = document_extraction_experiment.write_summary


class EchoFixtureDocument:
    def __init__(self, source: Path) -> None:
        self.source = source

    def export_to_markdown(self) -> str:
        if self.source.suffix in {".docx", ".pptx", ".pdf"}:
            return f"converted binary fixture includes {MARKER}"
        return self.source.read_text(encoding="utf-8")


class EchoFixtureConverter:
    def convert(self, source: Path | str) -> SimpleNamespace:
        return SimpleNamespace(document=EchoFixtureDocument(Path(source)))


def test_document_extraction_experiment_creates_synthetic_fixtures(tmp_path: Path) -> None:
    paths = create_synthetic_fixtures(tmp_path)

    assert {path.name for path in paths} == {
        "refund-note.docx",
        "refund-note.md",
        "refund-page.html",
        "refund-slide.pptx",
        "refund-summary.pdf",
    }
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)


def test_document_extraction_experiment_evaluates_converter_contract(
    tmp_path: Path,
) -> None:
    create_synthetic_fixtures(tmp_path)

    summary = evaluate_documents(tmp_path, converter=EchoFixtureConverter())

    assert summary["document_count"] == 5
    assert summary["ok_count"] == 5
    assert summary["marker_count"] == 5
    assert {
        result["content_type"] for result in summary["results"] if result["status"] == "ok"
    } >= {
        "application/pdf",
        "text/markdown",
        "text/html",
    }


def test_document_extraction_experiment_writes_summary(tmp_path: Path) -> None:
    summary = {"ok_count": 1, "results": []}
    output = tmp_path / "nested" / "summary.json"

    write_summary(summary, output)

    assert output.read_text(encoding="utf-8") == '{\n  "ok_count": 1,\n  "results": []\n}'


def test_docling_worker_dockerfile_keeps_docling_out_of_default_runtime() -> None:
    dockerfile = REPO_ROOT / "docker" / "docling-worker.Dockerfile"

    content = dockerfile.read_text(encoding="utf-8")

    assert "--mount=type=cache,target=/root/.cache/uv" in content
    assert "uv pip install docling" in content
    assert '"uv", "run", "--with", "docling"' not in content
    assert "scripts/evaluate_document_extraction.py" in content
    assert "ENTRYPOINT" in content


def test_compose_does_not_expose_docling_worker_experiment_service() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "docling-worker:" not in compose
    assert "dockerfile: docker/docling-worker.Dockerfile" not in compose
    assert ".local/document-extraction:/work/document-extraction" not in compose
