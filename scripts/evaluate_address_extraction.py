from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path

from gcb.etl.transform.pii import PresidioPiiDetector
from gcb.evaluation import evaluate_pii_detector, load_pii_eval_cases

ROOT = Path(__file__).resolve().parents[1]
ADDRESS_EVAL = ROOT / "fixtures" / "pii_eval" / "address_cases.json"


def main() -> None:
    cases = load_pii_eval_cases(ADDRESS_EVAL)
    baseline = PresidioPiiDetector(
        supported_languages=["en", "de"],
        enable_address_recognizer=False,
    )
    custom = PresidioPiiDetector(supported_languages=["en", "de"])

    output = {
        "case_count": len(cases),
        "results": {
            "presidio_without_address_recognizer": {
                "en": evaluate_pii_detector(baseline, cases, language="en").__dict__,
                "de": evaluate_pii_detector(baseline, cases, language="de").__dict__,
            },
            "presidio_with_narrow_address_recognizer": {
                "en": evaluate_pii_detector(custom, cases, language="en").__dict__,
                "de": evaluate_pii_detector(custom, cases, language="de").__dict__,
            },
        },
        "libpostal": {
            "python_binding_available": _libpostal_binding_available(),
            "v1_runtime_dependency": "deferred",
            "reason": "requires native libpostal model/runtime installation",
        },
        "recommendation": (
            "keep the narrow Presidio custom address recognizer for v1 synthetic coverage; "
            "defer libpostal to a dedicated service experiment before production address support"
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


def _libpostal_binding_available() -> bool:
    try:
        return find_spec("postal.parser") is not None
    except ModuleNotFoundError:
        return False


if __name__ == "__main__":
    main()
