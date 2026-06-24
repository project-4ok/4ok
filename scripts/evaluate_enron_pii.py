from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from fourok.etl.transform.pii import PresidioPiiDetector, spacy_model_available
from fourok.evaluation import evaluate_pii_detector, load_labeled_email_pii_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate local ignored Enron PII labels.")
    parser.add_argument(
        "--email-root",
        type=Path,
        default=Path(".local/enron-smoke/maildir"),
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path(".local/enron-smoke/pii-labels.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".local/enron-smoke/pii-eval-summary.json"),
    )
    args = parser.parse_args()

    cases = load_labeled_email_pii_cases(labels_path=args.labels, email_root=args.email_root)
    detectors = {
        "blank": PresidioPiiDetector(supported_languages=["en"], default_language="en"),
    }
    if spacy_model_available("en_core_web_sm"):
        detectors["en_core_web_sm"] = PresidioPiiDetector.with_spacy_model(
            language="en", model_name="en_core_web_sm"
        )

    summary = {
        "case_count": len(cases),
        "source_refs": [case.case_id for case in cases],
        "results": {
            name: asdict(evaluate_pii_detector(detector, cases, language="en"))
            for name, detector in detectors.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
