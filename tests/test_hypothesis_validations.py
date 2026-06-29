from pathlib import Path

import pytest

from fourok.etl.extract.email_parser import load_email_dir, path_for_source_ref
from fourok.etl.transform.pii import PresidioPiiDetector
from fourok.evaluation import (
    evaluate_pii_detector,
    load_labeled_email_pii_cases,
    load_pii_eval_cases,
)
from fourok.governance import GovernedContext

FIXTURES = Path(__file__).parent / "fixtures"
EMAILS = FIXTURES / "emails"
PII_EVAL = FIXTURES / "pii_eval" / "h5b_cases.json"
ADDRESS_EVAL = FIXTURES / "pii_eval" / "address_cases.json"
ENRON_SMOKE = Path(".local/enron-smoke/maildir")

RAW_SEEDED_VALUES = [
    "DE89370400440532013000",
    "anna.refunds@example.com",
    "+49 30 12345678",
    "finance+refunds@example.com",
    "+1 (415) 555-0134",
    "PMT-20260421",
    "DE89 3704 0044 0532 0130 00",
]


def test_h5b_english_spacy_model_improves_identity_detection() -> None:
    pytest.importorskip("en_core_web_sm")
    cases = load_pii_eval_cases(PII_EVAL)
    blank = PresidioPiiDetector(supported_languages=["en"], default_language="en")
    model = PresidioPiiDetector.with_spacy_model(language="en", model_name="en_core_web_sm")

    blank_result = evaluate_pii_detector(blank, cases, language="en")
    model_result = evaluate_pii_detector(model, cases, language="en")

    for token_type in ["email", "phone", "iban", "payment_identifier"]:
        assert model_result.matched_by_type[token_type] == blank_result.matched_by_type[token_type]

    assert model_result.matched_by_type["person"] > blank_result.matched_by_type.get("person", 0)
    assert model_result.matched_by_type["location"] > blank_result.matched_by_type.get(
        "location", 0
    )
    assert model_result.misses_by_type["address"] == 10


def test_h5b_model_backed_search_uses_raw_internal_content_without_reveal_tokens() -> None:
    pytest.importorskip("en_core_web_sm")
    PresidioPiiDetector.with_spacy_model(language="en", model_name="en_core_web_sm")
    context = GovernedContext()
    context.ingest(load_email_dir(EMAILS))

    response = context.search_context("DE89370400440532013000 canceled account", limit=3)
    serialized = str(response)

    assert not hasattr(response, "sensitive_tokens")
    assert "BANK_ACCOUNT_" not in serialized
    assert response.results[0].source_ref == "local_email:0013-refund-iban"
    assert "DE8937040044053" in serialized


def test_h10_snippet_only_answers_cover_seeded_customer_questions() -> None:
    context = GovernedContext()
    context.ingest(load_email_dir(EMAILS))
    questions = {
        "cancellation final invoice": "local_email:0001-cancellation-final-invoice",
        "refund bank transfer cancellation": "local_email:0002-refund-bank-transfer",
        "payment failed March invoice": "local_email:0004-payment-failed",
        "contract renewal legal": "local_email:0005-contract-renewal",
        "data export workspace archive": "local_email:0009-data-export",
        "billing address change": "local_email:0006-address-change",
        "support complaint unresolved": "local_email:0007-support-complaint",
        "upgrade additional seats priority support": "local_email:0010-upgrade-plan",
    }

    correct_with_citation = 0
    full_source_available = 0
    serialized_answers = []
    for query, expected_source_ref in questions.items():
        response = context.search_context(query, limit=3)
        source_refs = [result.source_ref for result in response.results]
        source_path = path_for_source_ref(EMAILS, expected_source_ref)
        answer = {
            "query": query,
            "source_refs": source_refs,
            "snippets": [result.snippet for result in response.results],
        }
        serialized_answers.append(str(answer))
        if expected_source_ref in source_refs:
            correct_with_citation += 1
        if source_path.read_text():
            full_source_available += 1

    assert correct_with_citation == 8
    assert full_source_available == 8
    assert any(raw_value in " ".join(serialized_answers) for raw_value in RAW_SEEDED_VALUES)


def test_h11_synthetic_source_refs_are_stable_and_human_resolvable() -> None:
    first_refs = [message.source_ref for message in load_email_dir(EMAILS)]
    second_refs = [message.source_ref for message in load_email_dir(EMAILS)]

    assert first_refs == second_refs

    refs_to_check = [
        "local_email:0001-cancellation-final-invoice",
        "local_email:0006-address-change",
        "local_email:0013-refund-iban",
        "local_email:0014-tricky-pii",
    ]
    for source_ref in refs_to_check:
        assert path_for_source_ref(EMAILS, source_ref).exists()

    context = GovernedContext()
    context.ingest(load_email_dir(EMAILS))
    response = context.search_context("refund bank transfer cancellation", limit=3)
    audit_event = context.audit_events()[0]
    assert response.results[0].source_ref in audit_event["source_refs"]


def test_h11_enron_source_refs_are_stable_when_local_subset_exists() -> None:
    if not ENRON_SMOKE.exists():
        pytest.skip("project-local Enron smoke subset is not present")

    first_refs = [message.source_ref for message in load_email_dir(ENRON_SMOKE)]
    second_refs = [message.source_ref for message in load_email_dir(ENRON_SMOKE)]
    refs_to_check = [
        "local_email:allen-p/inbox/1",
        "local_email:allen-p/inbox/4",
        "local_email:allen-p/inbox/28",
        "local_email:allen-p/inbox/51",
        "local_email:allen-p/inbox/60",
    ]

    assert first_refs == second_refs
    for source_ref in refs_to_check:
        assert path_for_source_ref(ENRON_SMOKE, source_ref).exists()


def test_h12_address_extraction_baseline_covers_simple_synthetic_cases() -> None:
    detector = PresidioPiiDetector(supported_languages=["en", "de"])
    cases = load_pii_eval_cases(ADDRESS_EVAL)

    english_result = evaluate_pii_detector(detector, cases, language="en")
    german_result = evaluate_pii_detector(detector, cases, language="de")

    assert english_result.matched_by_type["address"] == 3
    assert german_result.matched_by_type["address"] == 3
    assert english_result.false_positive_by_type == {}
    assert german_result.false_positive_by_type == {}


def test_h12_stock_presidio_does_not_cover_postal_address_spans() -> None:
    detector = PresidioPiiDetector(
        supported_languages=["en", "de"],
        enable_address_recognizer=False,
    )
    cases = load_pii_eval_cases(ADDRESS_EVAL)

    english_result = evaluate_pii_detector(detector, cases, language="en")
    german_result = evaluate_pii_detector(detector, cases, language="de")

    assert english_result.expected_by_type == {"address": 3}
    assert german_result.expected_by_type == {"address": 3}
    assert english_result.matched_by_type.get("address", 0) == 0
    assert german_result.matched_by_type.get("address", 0) == 0


def test_labeled_email_pii_cases_load_text_from_ignored_source_files(tmp_path: Path) -> None:
    email_root = tmp_path / "maildir"
    inbox = email_root / "sample" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "1").write_text(
        "\n".join(
            [
                "Subject: Account follow-up",
                "From: Sender <sender@example.com>",
                "To: Receiver <receiver@example.com>",
                "",
                "Call Jane Example at +1 (415) 555-0101.",
            ]
        )
    )
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(
        """
        [
          {
            "source_ref": "local_email:sample/inbox/1",
            "language": "en",
            "expected": [
              {"type": "email", "value": "sender@example.com"},
              {"type": "phone", "value": "+1 (415) 555-0101"}
            ]
          }
        ]
        """
    )

    cases = load_labeled_email_pii_cases(labels_path=labels_path, email_root=email_root)
    result = evaluate_pii_detector(PresidioPiiDetector(), cases, language="en")

    assert result.expected_by_type == {"email": 1, "phone": 1}
    assert result.matched_by_type == {"email": 1, "phone": 1}
