from pathlib import Path

from fourok.etl.extract.email_parser import (
    load_email_dir,
    load_email_dir_with_report,
    parse_email_file,
)

FIXTURES = Path(__file__).parents[3] / "fixtures" / "emails"


def test_parse_email_extracts_core_fields() -> None:
    message = parse_email_file(FIXTURES / "0001-cancellation-final-invoice.eml")

    assert message.source_ref == "local_email:0001-cancellation-final-invoice"
    assert message.subject == "Cancellation and final invoice"
    assert message.from_address == "anna.customer@example.com"
    assert message.to_addresses == ["support@example.com"]
    assert message.date == "2026-04-18T10:12:00+00:00"
    assert "requested cancellation" in message.body


def test_source_ref_is_stable_and_based_on_filename() -> None:
    first = parse_email_file(FIXTURES / "0008-final-invoice-paid.eml")
    second = parse_email_file(FIXTURES / "0008-final-invoice-paid.eml")

    assert first.source_ref == second.source_ref == "local_email:0008-final-invoice-paid"


def test_load_email_dir_recurses_through_maildir_style_files(tmp_path: Path) -> None:
    inbox = tmp_path / "maildir" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "42").write_text(
        "\n".join(
            [
                "From: operations@example.com",
                "To: support@example.com",
                "Date: Tue, 21 May 2026 08:00:00 +0000",
                "Subject: Maildir style message",
                "",
                "This message has no file extension.",
            ]
        )
    )

    messages = load_email_dir(tmp_path)

    assert len(messages) == 1
    assert messages[0].source_ref == "local_email:maildir/inbox/42"
    assert messages[0].subject == "Maildir style message"


def test_load_email_dir_reports_malformed_files(tmp_path: Path) -> None:
    (tmp_path / "valid.eml").write_text(
        "\n".join(
            [
                "From: valid@example.com",
                "To: support@example.com",
                "Date: Tue, 21 May 2026 08:00:00 +0000",
                "Subject: Valid message",
                "",
                "Useful body.",
            ]
        )
    )
    (tmp_path / "empty").write_text("")

    report = load_email_dir_with_report(tmp_path)

    assert len(report.messages) == 1
    assert report.skipped == [
        {
            "path": "empty",
            "reason": "missing headers and body",
        }
    ]


def test_parse_email_uses_html_body_when_plain_text_is_unavailable(tmp_path: Path) -> None:
    email_path = tmp_path / "html-only.eml"
    email_path.write_text(
        "\n".join(
            [
                "From: html@example.com",
                "To: support@example.com",
                "Date: Tue, 21 May 2026 08:00:00 +0000",
                "Subject: HTML only",
                "Content-Type: text/html; charset=utf-8",
                "",
                "<html><body><p>Desk heads should discuss market concerns.</p></body></html>",
            ]
        )
    )

    message = parse_email_file(email_path)

    assert "Desk heads should discuss market concerns." in message.body
    assert "<p>" not in message.body
