from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fourok.etl.extract.document_extraction import (
    DocumentConversionError,
    attachment_from_document,
    extract_document,
    extract_text_layer_pdf,
    land_raw_pdf,
    pdf_source_record,
)


class FakeDoclingDocument:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown

    def export_to_markdown(self) -> str:
        return self.markdown


class FakeDoclingConverter:
    def __init__(self, markdown: str = "# Refund\n\nIBAN DE89370400440532013000") -> None:
        self.markdown = markdown
        self.converted: list[Path] = []

    def convert(self, source: Path | str) -> SimpleNamespace:
        self.converted.append(Path(source))
        return SimpleNamespace(document=FakeDoclingDocument(self.markdown))


class FakePdfPage:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def extract_text(self) -> str | None:
        return self.text


class FakePdfReader:
    def __init__(self, pages: list[FakePdfPage]) -> None:
        self.pages = pages


def test_extract_document_uses_docling_converter_contract(tmp_path: Path) -> None:
    document_path = tmp_path / "refund-form.pdf"
    document_path.write_bytes(b"%PDF-1.4")
    converter = FakeDoclingConverter("  # Refund form\n\nAmount due 42 EUR\n")

    extracted = extract_document(document_path, converter=converter)

    assert converter.converted == [document_path]
    assert extracted.title == "refund-form.pdf"
    assert extracted.text == "# Refund form\n\nAmount due 42 EUR"
    assert extracted.source_path == document_path.as_posix()
    assert extracted.content_type == "application/pdf"


def test_attachment_from_document_returns_source_attachment(tmp_path: Path) -> None:
    document_path = tmp_path / "refund-note.docx"
    document_path.write_bytes(b"docx placeholder")

    attachment = attachment_from_document(
        document_path,
        attachment_ref="gmail:attachment:att-123",
        converter=FakeDoclingConverter("refund attachment searchable text"),
    )

    assert attachment.attachment_ref == "gmail:attachment:att-123"
    assert attachment.title == "refund-note.docx"
    assert attachment.text == "refund attachment searchable text"
    assert attachment.content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_attachment_from_document_defaults_attachment_ref_to_filename(tmp_path: Path) -> None:
    document_path = tmp_path / "receipt.unknown"
    document_path.write_bytes(b"unknown")

    attachment = attachment_from_document(document_path, converter=FakeDoclingConverter("text"))

    assert attachment.attachment_ref == "attachment:receipt.unknown"
    assert attachment.content_type == "application/octet-stream"


def test_extract_document_fails_clearly_when_docling_is_not_available(monkeypatch) -> None:
    def missing_docling_converter():
        raise DocumentConversionError(
            "Docling is required for document extraction; install docling to use this adapter."
        )

    monkeypatch.setattr(
        "fourok.etl.extract.document_extraction._docling_converter",
        missing_docling_converter,
    )

    with pytest.raises(DocumentConversionError, match="Docling is required"):
        extract_document("refund-form.pdf")


def test_extract_document_wraps_converter_failures(tmp_path: Path) -> None:
    class FailingConverter:
        def convert(self, source: Path | str) -> SimpleNamespace:
            raise ValueError(f"bad document: {source}")

    document_path = tmp_path / "bad.pdf"
    document_path.write_bytes(b"not really pdf")

    with pytest.raises(DocumentConversionError, match="Could not extract document text"):
        extract_document(document_path, converter=FailingConverter())


def test_extract_text_layer_pdf_reads_existing_pdf_text_only(tmp_path: Path) -> None:
    document_path = tmp_path / "contract.pdf"
    document_path.write_bytes(b"%PDF-1.4")

    extracted = extract_text_layer_pdf(
        document_path,
        reader=FakePdfReader(
            [
                FakePdfPage(" Contract heading \n"),
                FakePdfPage(None),
                FakePdfPage("Payment terms"),
            ]
        ),
    )

    assert extracted.title == "contract.pdf"
    assert extracted.text == "Contract heading\n\nPayment terms"
    assert extracted.source_path == document_path.as_posix()
    assert extracted.content_type == "application/pdf"


def test_extract_text_layer_pdf_rejects_non_pdf_and_pdf_without_text(tmp_path: Path) -> None:
    document_path = tmp_path / "image-only.pdf"
    document_path.write_bytes(b"%PDF-1.4")

    with pytest.raises(DocumentConversionError, match="requires .pdf"):
        extract_text_layer_pdf(tmp_path / "note.txt", reader=FakePdfReader([]))
    with pytest.raises(DocumentConversionError, match="no extractable text layer"):
        extract_text_layer_pdf(document_path, reader=FakePdfReader([FakePdfPage("  ")]))


def test_pdf_source_record_lands_raw_pdf_and_builds_document_record(tmp_path: Path) -> None:
    document_path = tmp_path / "contract.pdf"
    document_path.write_bytes(b"%PDF-1.4 fake text-layer pdf")
    landing_dir = tmp_path / "raw-pdf"

    record = pdf_source_record(
        document_path,
        landing_dir=landing_dir,
        source_system="google_drive",
        source_id="file-123",
        source_url="https://drive.example/file-123",
        permission_refs=("group:ops",),
        reader=FakePdfReader([FakePdfPage("Signed contract searchable text")]),
    )

    assert record.source_ref == "google_drive:document:file-123"
    assert record.source_system == "google_drive"
    assert record.source_id == "file-123"
    assert record.record_type == "document"
    assert record.title == "contract.pdf"
    assert record.body == "Signed contract searchable text"
    assert record.source_url == "https://drive.example/file-123"
    assert record.permission_refs == ("group:ops",)
    assert record.checksum.startswith("sha256:")
    assert record.version == record.checksum
    assert record.raw_ref.endswith(".pdf")
    assert Path(record.raw_ref).exists()
    assert Path(record.raw_ref).read_bytes() == document_path.read_bytes()
    assert record.metadata == {
        "content_type": "application/pdf",
        "source_path": document_path.as_posix(),
        "text_extraction": "pypdf_text_layer",
        "ocr_used": False,
    }


def test_land_raw_pdf_is_checksum_stable(tmp_path: Path) -> None:
    document_path = tmp_path / "contract.pdf"
    document_path.write_bytes(b"%PDF-1.4 stable")
    landing_dir = tmp_path / "raw-pdf"

    first = land_raw_pdf(document_path, landing_dir)
    second = land_raw_pdf(document_path, landing_dir)

    assert first == second
    assert first.path.exists()
