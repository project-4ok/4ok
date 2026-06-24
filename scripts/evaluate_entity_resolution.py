from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from gcb.etl.transform.entity_resolution import (
    display_name_email_alias_clusters,
    evaluate_clusters,
    exact_email_clusters,
    load_labeled_identities,
    review_candidates,
    splink_probability_clusters,
)

FIXTURE = Path("fixtures/entity_resolution/multi_source_identities.json")


def main() -> int:
    identities = load_labeled_identities(FIXTURE)
    methods = {
        "exact_email": exact_email_clusters(identities),
        "display_name_email_alias": display_name_email_alias_clusters(identities),
        "splink_probability": splink_probability_clusters(identities),
    }
    results = []
    for method, clusters in methods.items():
        candidates = review_candidates(identities, method=method, predicted_clusters=clusters)
        results.append(
            {
                "method": method,
                "metrics": asdict(evaluate_clusters(identities, clusters)),
                "candidate_count": len(candidates),
                "review_candidates": [
                    asdict(candidate) for candidate in candidates if candidate.decision == "review"
                ],
                "accepted_candidates": [
                    asdict(candidate) for candidate in candidates if candidate.decision == "accept"
                ],
            }
        )

    print(json.dumps({"fixture": str(FIXTURE), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
