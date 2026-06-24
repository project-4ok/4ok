from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from fourok.etl.extract.email_parser import load_email_dir
from fourok.governance import GovernedContext
from fourok.retrieval.evaluation import compare_retrieval_methods, load_retrieval_eval_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval methods on local fixtures.")
    parser.add_argument("--emails", type=Path, default=Path("fixtures/emails"))
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/retrieval_eval/customer_context_queries.json"),
    )
    parser.add_argument("--output", type=Path, default=Path(".local/retrieval-eval-summary.json"))
    args = parser.parse_args()

    context = GovernedContext()
    context.ingest(load_email_dir(args.emails))
    vector_index = context.build_vector_index()
    cases = load_retrieval_eval_cases(args.cases)
    metrics = compare_retrieval_methods(context, vector_index, cases)
    summary = {
        "case_count": len(cases),
        "metrics": [
            {
                **asdict(metric),
                "top1_rate": metric.top1_rate,
                "top3_rate": metric.top3_rate,
            }
            for metric in metrics
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
