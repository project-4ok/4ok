import pytest

from gcb.etl.transform.pii import PresidioPiiDetector, spacy_model_available


def test_presidio_detector_finds_seeded_identifiers() -> None:
    detector = PresidioPiiDetector()
    text = (
        "Email anna.refunds@example.com, call +49 30 12345678, "
        "and refund IBAN DE89370400440532013000."
    )

    findings = detector.find(text)

    detected = {(finding.token_type, finding.raw_value) for finding in findings}
    assert ("email", "anna.refunds@example.com") in detected
    assert ("phone", "+49 30 12345678") in detected
    assert ("iban", "DE89370400440532013000") in detected


def test_presidio_detector_finds_tricky_synthetic_identifiers() -> None:
    detector = PresidioPiiDetector()
    text = (
        'Contact "finance+refunds@example.com", call +1 (415) 555-0134, '
        "and reconcile payment reference PMT-20260421. "
        "The IBAN was written as DE89 3704 0044 0532 0130 00."
    )

    findings = detector.find(text)

    detected = {(finding.token_type, finding.raw_value) for finding in findings}
    assert ("email", "finance+refunds@example.com") in detected
    assert ("phone", "+1 (415) 555-0134") in detected
    assert ("payment_identifier", "PMT-20260421") in detected
    assert ("iban", "DE89 3704 0044 0532 0130 00") in detected


def test_presidio_detector_finds_narrow_address_baseline() -> None:
    detector = PresidioPiiDetector()
    text = "Ship the refund letter to 12 Market Street and archive Sonnenweg 4."

    findings = detector.find(text)

    detected = {(finding.token_type, finding.raw_value) for finding in findings}
    assert ("address", "12 Market Street") in detected
    assert ("address", "Sonnenweg 4") in detected


def test_spacy_model_backed_detector_requires_installed_model() -> None:
    model_name = "gcb_missing_spacy_model"

    assert not spacy_model_available(model_name)
    with pytest.raises(RuntimeError, match="uv run python -m spacy download"):
        PresidioPiiDetector.with_spacy_model(language="en", model_name=model_name)
