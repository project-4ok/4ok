from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path


@dataclass(frozen=True)
class EmailMessage:
    source_ref: str
    subject: str
    from_address: str
    to_addresses: list[str]
    date: str
    body: str


@dataclass(frozen=True)
class LoadReport:
    messages: list[EmailMessage]
    skipped: list[dict[str, str]]


def load_email_dir(path: Path) -> list[EmailMessage]:
    return load_email_dir_with_report(path).messages


def load_email_dir_with_report(path: Path) -> LoadReport:
    messages: list[EmailMessage] = []
    skipped: list[dict[str, str]] = []

    for email_path in _email_paths(path):
        try:
            message = parse_email_file(email_path, root=path)
        except ValueError as error:
            skipped.append({"path": _display_path(email_path, path), "reason": str(error)})
            continue
        messages.append(message)

    return LoadReport(messages=messages, skipped=skipped)


def parse_email_file(path: Path, *, root: Path | None = None) -> EmailMessage:
    with path.open("rb") as email_file:
        raw_message = BytesParser(policy=policy.default).parse(email_file)

    subject = str(raw_message.get("subject", ""))
    from_address = _first_address(raw_message.get_all("from", []))
    to_addresses = _addresses(raw_message.get_all("to", []))
    date = _date(raw_message.get("date"))
    body = _body(raw_message)

    if not any([subject, from_address, to_addresses, date, body]):
        raise ValueError("missing headers and body")

    if not body:
        raise ValueError("missing body")

    return EmailMessage(
        source_ref=f"local_email:{_source_id(path, root)}",
        subject=str(raw_message.get("subject", "")),
        from_address=from_address,
        to_addresses=to_addresses,
        date=date,
        body=body,
    )


def path_for_source_ref(root: Path, source_ref: str) -> Path:
    prefix = "local_email:"
    if not source_ref.startswith(prefix):
        raise ValueError(f"Unsupported source ref: {source_ref}")

    source_id = source_ref.removeprefix(prefix)
    direct_path = root / source_id
    if direct_path.exists():
        return direct_path

    eml_path = direct_path.with_suffix(".eml")
    if eml_path.exists():
        return eml_path

    raise FileNotFoundError(f"No local source file found for {source_ref}")


def _email_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob("*") if candidate.is_file())


def _display_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _source_id(path: Path, root: Path | None) -> str:
    if root is None:
        return path.stem

    relative = path.relative_to(root)
    if relative.suffix == ".eml":
        relative = relative.with_suffix("")
    return relative.as_posix()


def _first_address(values: list[str]) -> str:
    addresses = _addresses(values)
    if not addresses:
        return ""
    return addresses[0]


def _addresses(values: list[str]) -> list[str]:
    return [email_address for _, email_address in getaddresses(values) if email_address]


def _date(value: str | None) -> str:
    if not value:
        return ""
    return parsedate_to_datetime(value).isoformat()


def _body(raw_message) -> str:
    if raw_message.is_multipart():
        plain_parts = [
            _decode_part(part, strip_html=False)
            for part in raw_message.walk()
            if part.get_content_type() == "text/plain"
            and part.get_content_disposition() != "attachment"
        ]
        if any(plain_parts):
            return "\n".join(part for part in plain_parts if part).strip()

        html_parts = [
            _decode_part(part, strip_html=True)
            for part in raw_message.walk()
            if part.get_content_type() == "text/html"
            and part.get_content_disposition() != "attachment"
        ]
        return "\n".join(part for part in html_parts if part).strip()

    return _decode_part(
        raw_message,
        strip_html=raw_message.get_content_type() == "text/html",
    ).strip()


def _decode_part(part, *, strip_html: bool) -> str:
    payload = part.get_payload(decode=True)
    charset = part.get_content_charset() or "utf-8"
    if payload is None:
        text = part.get_payload()
        decoded = text if isinstance(text, str) else ""
    else:
        decoded = payload.decode(charset, errors="replace")

    if strip_html:
        return _html_to_text(decoded)
    return decoded


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return " ".join(parser.text.split())


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(self._parts)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data.strip())
