from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fourok.etl.extract.email_parser import load_email_dir
from fourok.etl.transform.pii import PresidioPiiDetector


@dataclass(frozen=True)
class ExpectedPii:
    token_type: str
    value: str


@dataclass(frozen=True)
class PiiEvalCase:
    case_id: str
    language: str
    text: str
    expected: list[ExpectedPii]


@dataclass(frozen=True)
class PiiEvalResult:
    expected_by_type: dict[str, int]
    matched_by_type: dict[str, int]
    false_positive_by_type: dict[str, int]
    misses_by_type: dict[str, int]


def load_pii_eval_cases(path: Path) -> list[PiiEvalCase]:
    raw_cases = json.loads(path.read_text())
    return [
        PiiEvalCase(
            case_id=raw_case["id"],
            language=raw_case["language"],
            text=raw_case["text"],
            expected=[
                ExpectedPii(token_type=item["type"], value=item["value"])
                for item in raw_case["expected"]
            ],
        )
        for raw_case in raw_cases
    ]


def load_labeled_email_pii_cases(*, labels_path: Path, email_root: Path) -> list[PiiEvalCase]:
    messages_by_source_ref = {message.source_ref: message for message in load_email_dir(email_root)}
    raw_cases = json.loads(labels_path.read_text())
    cases: list[PiiEvalCase] = []

    for raw_case in raw_cases:
        source_ref = raw_case["source_ref"]
        message = messages_by_source_ref[source_ref]
        text = "\n".join(
            part
            for part in [
                message.subject,
                message.from_address,
                " ".join(message.to_addresses),
                message.body,
            ]
            if part
        )
        cases.append(
            PiiEvalCase(
                case_id=source_ref,
                language=raw_case.get("language", "en"),
                text=text,
                expected=[
                    ExpectedPii(token_type=item["type"], value=item["value"])
                    for item in raw_case["expected"]
                ],
            )
        )

    return cases


def evaluate_pii_detector(
    detector: PresidioPiiDetector,
    cases: list[PiiEvalCase],
    *,
    language: str,
) -> PiiEvalResult:
    selected_cases = [case for case in cases if case.language == language]
    expected_by_type: Counter[str] = Counter()
    matched_by_type: Counter[str] = Counter()
    false_positive_by_type: Counter[str] = Counter()
    misses_by_type: Counter[str] = Counter()

    for case in selected_cases:
        expected = case.expected
        findings = detector.find(case.text, language=language)
        expected_by_type.update(item.token_type for item in expected)

        matched_indexes: set[int] = set()
        for finding in findings:
            matched_index = next(
                (
                    index
                    for index, item in enumerate(expected)
                    if index not in matched_indexes
                    and finding.token_type == item.token_type
                    and _text_overlaps(finding.raw_value, item.value)
                ),
                None,
            )
            if matched_index is None:
                false_positive_by_type[finding.token_type] += 1
                continue
            matched_indexes.add(matched_index)
            matched_by_type[finding.token_type] += 1

        for index, item in enumerate(expected):
            if index not in matched_indexes:
                misses_by_type[item.token_type] += 1

    return PiiEvalResult(
        expected_by_type=dict(sorted(expected_by_type.items())),
        matched_by_type=dict(sorted(matched_by_type.items())),
        false_positive_by_type=dict(sorted(false_positive_by_type.items())),
        misses_by_type=dict(sorted(misses_by_type.items())),
    )


def _text_overlaps(left: str, right: str) -> bool:
    normalized_left = " ".join(left.lower().split())
    normalized_right = " ".join(right.lower().split())
    return normalized_left in normalized_right or normalized_right in normalized_left
