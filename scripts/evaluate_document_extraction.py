from __future__ import annotations

import argparse
import json
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from gcb.etl.extract.document_extraction import (
    DocumentConversionError,
    attachment_from_document,
)

DEFAULT_INPUT_DIR = Path(".local/document-extraction/inputs")
DEFAULT_OUTPUT = Path(".local/document-extraction/summary.json")
MARKER = "DOC_EXTRACTION_SMOKE_MARKER"


@dataclass(frozen=True)
class DocumentExtractionResult:
    path: str
    content_type: str
    status: str
    char_count: int
    contains_marker: bool
    duration_seconds: float
    error: str = ""


def create_synthetic_fixtures(input_dir: Path) -> list[Path]:
    input_dir.mkdir(parents=True, exist_ok=True)
    documents = {
        "refund-note.md": f"# Refund note\n\nCustomer context includes {MARKER}.\n",
        "refund-page.html": (
            "<html><body><h1>Refund page</h1>"
            f"<p>Customer context includes {MARKER}.</p></body></html>"
        ),
    }
    for name, text in documents.items():
        (input_dir / name).write_text(text, encoding="utf-8")

    _write_minimal_docx(input_dir / "refund-note.docx")
    _write_minimal_pptx(input_dir / "refund-slide.pptx")
    _write_minimal_pdf(input_dir / "refund-summary.pdf")
    return sorted(input_dir.iterdir())


def evaluate_documents(input_dir: Path, *, converter=None) -> dict[str, object]:
    paths = sorted(path for path in input_dir.iterdir() if path.is_file())
    results = [_evaluate_document(path, converter=converter) for path in paths]
    ok_results = [result for result in results if result.status == "ok"]
    marker_results = [result for result in ok_results if result.contains_marker]
    return {
        "input_dir": input_dir.as_posix(),
        "document_count": len(paths),
        "ok_count": len(ok_results),
        "marker_count": len(marker_results),
        "results": [asdict(result) for result in results],
    }


def write_summary(summary: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate optional Docling document extraction.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--create-fixtures",
        action="store_true",
        help="Create synthetic markdown/html/docx/pptx/pdf smoke fixtures first.",
    )
    args = parser.parse_args()

    if args.create_fixtures:
        create_synthetic_fixtures(args.input_dir)

    summary = evaluate_documents(args.input_dir)
    write_summary(summary, args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok_count"] else 1


def _evaluate_document(path: Path, *, converter=None) -> DocumentExtractionResult:
    started = time.perf_counter()
    try:
        attachment = attachment_from_document(path, converter=converter)
    except DocumentConversionError as error:
        duration = time.perf_counter() - started
        return DocumentExtractionResult(
            path=path.as_posix(),
            content_type="",
            status="error",
            char_count=0,
            contains_marker=False,
            duration_seconds=round(duration, 4),
            error=str(error),
        )

    duration = time.perf_counter() - started
    return DocumentExtractionResult(
        path=path.as_posix(),
        content_type=attachment.content_type,
        status="ok",
        char_count=len(attachment.text),
        contains_marker=MARKER in attachment.text,
        duration_seconds=round(duration, 4),
    )


def _write_minimal_docx(path: Path) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Customer context includes {MARKER}.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" """
                """ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" """
                """ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml."""
                """document.main+xml"/>
</Types>
"""
            ),
        )
        archive.writestr(
            "_rels/.rels",
            (
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" """
                """Type="http://schemas.openxmlformats.org/officeDocument/2006/"""
                """relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
            ),
        )
        archive.writestr("word/document.xml", document_xml)


def _write_minimal_pptx(path: Path) -> None:
    slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="TextBox 1"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:txBody><a:bodyPr/><a:lstStyle/>
          <a:p><a:r><a:t>Customer context includes {MARKER}.</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" """
                """ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" """
                """ContentType="application/vnd.openxmlformats-officedocument.presentationml."""
                """presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" """
                """ContentType="application/vnd.openxmlformats-officedocument.presentationml."""
                """slide+xml"/>
</Types>
"""
            ),
        )
        archive.writestr(
            "_rels/.rels",
            (
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" """
                """Type="http://schemas.openxmlformats.org/officeDocument/2006/"""
                """relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>
"""
            ),
        )
        archive.writestr(
            "ppt/presentation.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>
</p:presentation>
""",
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            (
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" """
                """Type="http://schemas.openxmlformats.org/officeDocument/2006/"""
                """relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
"""
            ),
        )
        archive.writestr("ppt/slides/slide1.xml", slide_xml)


def _write_minimal_pdf(path: Path) -> None:
    stream = f"BT /F1 12 Tf 72 720 Td (Customer context includes {MARKER}.) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    parts = ["%PDF-1.4\n"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(part.encode("latin-1")) for part in parts))
        parts.append(f"{index} 0 obj\n{body}\nendobj\n")
    xref_offset = sum(len(part.encode("latin-1")) for part in parts)
    parts.append(f"xref\n0 {len(objects) + 1}\n")
    parts.append("0000000000 65535 f \n")
    for offset in offsets[1:]:
        parts.append(f"{offset:010d} 00000 n \n")
    parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    )
    path.write_bytes("".join(parts).encode("latin-1"))


if __name__ == "__main__":
    raise SystemExit(main())
