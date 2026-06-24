"""Deferred PII-detection experiment.

PII detection is not part of the current source-record import/search runtime.
Keep usage isolated to explicit experiments until tokenization is implemented
consistently for every source surface.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib.util import find_spec

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngine, NlpEngineProvider


@dataclass(frozen=True)
class PiiFinding:
    token_type: str
    raw_value: str
    start: int
    end: int
    score: float


class PresidioPiiDetector:
    def __init__(
        self,
        *,
        nlp_engine: NlpEngine | None = None,
        supported_languages: list[str] | None = None,
        default_language: str = "en",
        enable_address_recognizer: bool = True,
    ) -> None:
        self._supported_languages = supported_languages or ["en"]
        self._default_language = default_language
        self._enable_address_recognizer = enable_address_recognizer
        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine or _BlankNlpEngine(self._supported_languages),
            supported_languages=self._supported_languages,
        )
        self._add_custom_recognizers()

    @classmethod
    def with_spacy_model(
        cls,
        *,
        language: str,
        model_name: str,
        enable_address_recognizer: bool = True,
    ) -> PresidioPiiDetector:
        if not spacy_model_available(model_name):
            raise RuntimeError(
                f"spaCy model {model_name!r} is not installed. "
                f"Install it with: uv run python -m spacy download {model_name}"
            )
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": language, "model_name": model_name}],
            }
        )
        return cls(
            nlp_engine=provider.create_engine(),
            supported_languages=[language],
            default_language=language,
            enable_address_recognizer=enable_address_recognizer,
        )

    def find(self, text: str, *, language: str | None = None) -> list[PiiFinding]:
        if not text:
            return []

        analysis_language = language or self._default_language
        results = self._analyzer.analyze(
            text=text,
            language=analysis_language,
            entities=[
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "IBAN",
                "PAYMENT_IDENTIFIER",
                "ADDRESS",
                "PERSON",
                "ORGANIZATION",
                "LOCATION",
            ],
        )
        findings = [
            PiiFinding(
                token_type=_TOKEN_TYPE_BY_ENTITY[result.entity_type],
                raw_value=text[result.start : result.end],
                start=result.start,
                end=result.end,
                score=result.score,
            )
            for result in results
            if result.entity_type in _TOKEN_TYPE_BY_ENTITY
        ]
        return _deduplicate_overlaps(findings)

    def _add_custom_recognizers(self) -> None:
        for language in self._supported_languages:
            recognizers = [
                PatternRecognizer(
                    supported_entity="IBAN",
                    supported_language=language,
                    patterns=[
                        Pattern(
                            name="iban_contiguous",
                            regex=r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
                            score=0.85,
                        ),
                        Pattern(
                            name="iban_spaced",
                            regex=(
                                r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}"
                                r"(?: ?[A-Z0-9]{1,4})?\b"
                            ),
                            score=0.8,
                        ),
                    ],
                ),
                PatternRecognizer(
                    supported_entity="PAYMENT_IDENTIFIER",
                    supported_language=language,
                    patterns=[
                        Pattern(
                            name="payment_reference",
                            regex=r"\b(?:PAY|PMT|REF|TXN|INV)-\d{4,12}\b",
                            score=0.75,
                        )
                    ],
                ),
            ]
            if self._enable_address_recognizer:
                recognizers.append(
                    PatternRecognizer(
                        supported_entity="ADDRESS",
                        supported_language=language,
                        patterns=[
                            Pattern(
                                name="street_address_suffix",
                                regex=(
                                    r"\b\d{1,5}\s+[A-Z][A-Za-z]+"
                                    r"(?:\s+[A-Z][A-Za-z]+){0,3}\s+"
                                    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|"
                                    r"Boulevard|Blvd|Way)\b"
                                ),
                                score=0.65,
                            ),
                            Pattern(
                                name="german_street_address",
                                regex=(
                                    r"\b[A-Z][A-Za-z]*(?:strasse|straße|weg|platz|allee)"
                                    r"\s+\d{1,5}[a-zA-Z]?\b"
                                ),
                                score=0.65,
                            ),
                        ],
                    )
                )

            for recognizer in recognizers:
                self._analyzer.registry.add_recognizer(recognizer)


class _BlankNlpEngine(NlpEngine):
    def __init__(self, supported_languages: list[str]) -> None:
        self._models = {language: spacy.blank(language) for language in supported_languages}

    def load(self) -> None:
        return None

    def is_loaded(self) -> bool:
        return True

    def process_text(self, text: str, language: str) -> NlpArtifacts:
        doc = self._models[language](text)
        return NlpArtifacts(
            entities=[],
            tokens=doc,
            tokens_indices=[token.idx for token in doc],
            lemmas=[token.lemma_ for token in doc],
            nlp_engine=self,
            language=language,
        )

    def process_batch(
        self,
        texts: Iterable[str],
        language: str,
        batch_size: int = 1,
        n_process: int = 1,
        **kwargs: object,
    ) -> Iterator[tuple[str, NlpArtifacts]]:
        for text in texts:
            yield text, self.process_text(text, language)

    def is_stopword(self, word: str, language: str) -> bool:
        return self._models[language].vocab[word].is_stop

    def is_punct(self, word: str, language: str) -> bool:
        return self._models[language].vocab[word].is_punct

    def get_supported_entities(self) -> list[str]:
        return []

    def get_supported_languages(self) -> list[str]:
        return list(self._models)


def spacy_model_available(model_name: str) -> bool:
    try:
        return find_spec(model_name) is not None
    except ModuleNotFoundError:
        return False


def _deduplicate_overlaps(findings: list[PiiFinding]) -> list[PiiFinding]:
    sorted_findings = sorted(
        findings,
        key=lambda finding: (
            -_TOKEN_PRIORITY.get(finding.token_type, 0),
            -finding.score,
            -(finding.end - finding.start),
            finding.start,
        ),
    )
    selected: list[PiiFinding] = []
    occupied: set[int] = set()

    for finding in sorted_findings:
        span = set(range(finding.start, finding.end))
        if occupied.intersection(span):
            continue
        selected.append(finding)
        occupied.update(span)

    return sorted(selected, key=lambda finding: finding.start)


_TOKEN_PRIORITY = {
    "email": 100,
    "phone": 100,
    "iban": 100,
    "payment_identifier": 100,
    "address": 90,
    "person": 50,
    "organization": 50,
    "location": 50,
}


_TOKEN_TYPE_BY_ENTITY = {
    "EMAIL_ADDRESS": "email",
    "PHONE_NUMBER": "phone",
    "IBAN": "iban",
    "PAYMENT_IDENTIFIER": "payment_identifier",
    "ADDRESS": "address",
    "PERSON": "person",
    "ORGANIZATION": "organization",
    "LOCATION": "location",
}
