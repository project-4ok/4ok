from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from gcb.etl.extract.source_records import SourceAttachment, SourceRecord
from gcb.observability import critical_span, set_safe_span_attributes


class DocumentConversionError(RuntimeError):
    pass


class _Document(Protocol):
    def export_to_markdown(self) -> str: ...


class _ConversionResult(Protocol):
    document: _Document


class _DocumentConverter(Protocol):
    def convert(self, source: Path | str) -> _ConversionResult: ...


class _PdfPage(Protocol):
    def extract_text(self) -> str | None: ...


class _PdfReader(Protocol):
    pages: list[_PdfPage]


@dataclass(frozen=True)
class ExtractedDocument:
    title: str
    text: str
    source_path: str
    content_type: str


@dataclass(frozen=True)
class LandedPdf:
    raw_ref: str
    path: Path
    checksum: str


def extract_document(
    path: Path | str,
    *,
    converter: _DocumentConverter | None = None,
) -> ExtractedDocument:
    document_path = Path(path)
    active_converter = converter or _docling_converter()

    with critical_span(
        "gcb.document.extract",
        attributes={
            "gcb.document.extractor": "docling",
            "gcb.document.extension": document_path.suffix.lower(),
        },
        status_attribute="gcb.document.status",
    ) as span:
        try:
            result = active_converter.convert(document_path)
            text = result.document.export_to_markdown().strip()
        except Exception as error:
            raise DocumentConversionError(
                f"Could not extract document text from {document_path}"
            ) from error

        extracted = ExtractedDocument(
            title=document_path.name,
            text=text,
            source_path=document_path.as_posix(),
            content_type=_content_type(document_path),
        )
        set_safe_span_attributes(
            span,
            {
                "gcb.document.status": "succeeded",
                "gcb.document.content_type": extracted.content_type,
                "gcb.document.text_length": len(extracted.text),
            },
        )
        return extracted


def extract_text_layer_pdf(
    path: Path | str,
    *,
    reader: _PdfReader | None = None,
) -> ExtractedDocument:
    document_path = Path(path)
    with critical_span(
        "gcb.document.extract",
        attributes={
            "gcb.document.extractor": "pypdf_text_layer",
            "gcb.document.extension": document_path.suffix.lower(),
        },
        status_attribute="gcb.document.status",
    ) as span:
        if document_path.suffix.lower() != ".pdf":
            raise DocumentConversionError(
                f"Text-layer PDF extraction requires .pdf: {document_path}"
            )
        active_reader = reader or _pypdf_reader(document_path)
        text = "\n\n".join(
            page_text.strip()
            for page in active_reader.pages
            if (page_text := page.extract_text())
            if page_text.strip()
        ).strip()
        if not text:
            raise DocumentConversionError(f"PDF has no extractable text layer: {document_path}")
        extracted = ExtractedDocument(
            title=document_path.name,
            text=text,
            source_path=document_path.as_posix(),
            content_type="application/pdf",
        )
        set_safe_span_attributes(
            span,
            {
                "gcb.document.status": "succeeded",
                "gcb.document.content_type": extracted.content_type,
                "gcb.document.text_length": len(extracted.text),
            },
        )
        return extracted


def land_raw_pdf(path: Path | str, landing_dir: Path | str) -> LandedPdf:
    with critical_span(
        "gcb.raw_landing.document",
        attributes={"gcb.document.extension": Path(path).suffix.lower()},
        status_attribute="gcb.raw_landing.status",
    ) as span:
        document_path = Path(path)
        checksum = _file_checksum(document_path)
        destination_dir = Path(landing_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{checksum.removeprefix('sha256:')}.pdf"
        if not destination.exists():
            shutil.copy2(document_path, destination)
        set_safe_span_attributes(
            span,
            {
                "gcb.raw_landing.status": "succeeded",
                "gcb.raw_landing.record_count": 1,
            },
        )
        return LandedPdf(raw_ref=destination.as_posix(), path=destination, checksum=checksum)


def pdf_source_record(
    path: Path | str,
    *,
    landing_dir: Path | str | None = None,
    source_ref: str | None = None,
    source_system: str = "pdf",
    source_id: str | None = None,
    source_url: str = "",
    permission_refs: tuple[str, ...] = (),
    reader: _PdfReader | None = None,
) -> SourceRecord:
    document_path = Path(path)
    extracted = extract_text_layer_pdf(document_path, reader=reader)
    landed = land_raw_pdf(document_path, landing_dir) if landing_dir is not None else None
    checksum = landed.checksum if landed is not None else _file_checksum(document_path)
    stable_id = source_id or checksum.removeprefix("sha256:")
    return SourceRecord(
        source_ref=source_ref or f"{source_system}:document:{stable_id[:16]}",
        source_system=source_system,
        source_id=stable_id,
        record_type="document",
        title=extracted.title,
        body=extracted.text,
        source_url=source_url or document_path.as_posix(),
        permission_refs=permission_refs,
        checksum=checksum,
        version=checksum,
        metadata={
            "content_type": extracted.content_type,
            "source_path": extracted.source_path,
            "text_extraction": "pypdf_text_layer",
            "ocr_used": False,
        },
        raw_ref=landed.raw_ref if landed is not None else "",
        raw={
            "source_path": extracted.source_path,
            "content_type": extracted.content_type,
            "checksum": checksum,
        },
    )


def attachment_from_document(
    path: Path | str,
    *,
    attachment_ref: str | None = None,
    converter: _DocumentConverter | None = None,
) -> SourceAttachment:
    extracted = extract_document(path, converter=converter)
    return SourceAttachment(
        attachment_ref=attachment_ref or f"attachment:{Path(path).name}",
        title=extracted.title,
        text=extracted.text,
        content_type=extracted.content_type,
    )


def _docling_converter() -> _DocumentConverter:
    try:
        from docling.document_converter import DocumentConverter
    except ModuleNotFoundError as error:
        raise DocumentConversionError(
            "Docling is required for document extraction; install docling to use this adapter."
        ) from error

    return DocumentConverter()


def _pypdf_reader(path: Path) -> _PdfReader:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as error:
        raise DocumentConversionError("pypdf is required for text-layer PDF extraction.") from error
    try:
        return PdfReader(path)
    except Exception as error:
        raise DocumentConversionError(f"Could not read PDF text layer from {path}") from error


def _content_type(path: Path) -> str:
    guessed_type, _ = mimetypes.guess_type(path.name)
    return guessed_type or "application/octet-stream"


def _file_checksum(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"
