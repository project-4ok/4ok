from __future__ import annotations

import argparse
import json
from typing import cast

from gcb.cli_parts.runtime_helpers import _database_url_from_args
from gcb.cli_parts.shared import DEFAULT_STATE, _principal_from_args
from gcb.etl.extract.email_parser import load_email_dir_with_report
from gcb.governance import GovernedContext
from gcb.retrieval.augmentation import RetrieverName
from gcb.retrieval.live_retrieval_case_set import run_live_retrieval_case_set
from gcb.runtime.operator_live import host_database_url
from gcb.workflows import HumanAgentWorkflow


def dispatch_search_commands(args: argparse.Namespace) -> bool:
    database_url = _database_url_from_args(args)
    if args.command == "search":
        load_report = load_email_dir_with_report(args.emails)
        context = GovernedContext(args.state, database_url=database_url)
        context.ingest(load_report.messages)
        response = context.search_context(args.query, limit=args.limit)
        results = response.results
        print(
            json.dumps(
                {
                    "query": args.query,
                    "load": {
                        "loaded": len(load_report.messages),
                        "skipped": len(load_report.skipped),
                        "skipped_files": load_report.skipped,
                    },
                    "results": [result.__dict__ for result in results],
                },
                indent=2,
            )
        )
        return True

    if args.command == "search-state":
        context = GovernedContext(args.state, database_url=database_url)
        response = context.search_context(
            args.query,
            limit=args.limit,
            principal=_principal_from_args(args),
        )
        print(
            json.dumps(
                {
                    "query": args.query,
                    "load": {"loaded": 0, "source": "existing_state"},
                    "results": [result.__dict__ for result in response.results],
                    "summary": response.summary,
                    "result_candidates": response.result_candidates,
                    "evidence_items": response.evidence_items,
                    "primary_objects": response.primary_objects,
                    "related_objects": response.related_objects,
                    "related_object_groups": response.related_object_groups,
                    "entities": response.entities,
                    "unresolved_candidates": response.unresolved_candidates,
                    "limitations": response.limitations,
                    "audit_ref": response.audit_ref,
                },
                indent=2,
            )
        )
        return True

    if args.command == "retrieve":
        context = GovernedContext(args.state, database_url=database_url)
        retrievers = tuple(item.strip() for item in str(args.retrievers).split(",") if item.strip())
        invalid = sorted(set(retrievers) - {"keyword", "vector"})
        if invalid:
            raise SystemExit(f"Unsupported retriever(s): {', '.join(invalid)}")
        response = context.retrieve_augmentation(
            args.query,
            limit=5,
            candidate_limit=args.candidate_limit,
            retrievers=cast(tuple[RetrieverName, ...], retrievers),
        )
        if args.format == "json":
            print(json.dumps(response.to_dict(), indent=2))
        else:
            print(response.context_block, end="")
        return True

    if args.command == "ask":
        load_report = load_email_dir_with_report(args.emails)
        context = GovernedContext(args.state, database_url=database_url)
        context.ingest(load_report.messages)
        workflow = HumanAgentWorkflow(
            context,
            _principal_from_args(args),
        )
        response = workflow.ask(args.query, limit=args.limit)
        print(
            json.dumps(
                {
                    "query": args.query,
                    "summary": response.summary,
                    "evidence": [item.__dict__ for item in response.evidence],
                    "load": {
                        "loaded": len(load_report.messages),
                        "skipped": len(load_report.skipped),
                        "skipped_files": load_report.skipped,
                    },
                },
                indent=2,
            )
        )
        return True

    if args.command == "live-retrieval-case-set":
        live_database_url = _database_url_from_args(args)
        if getattr(args, "state", DEFAULT_STATE) == DEFAULT_STATE and live_database_url:
            live_database_url = host_database_url(live_database_url)
        context = GovernedContext(
            args.state,
            database_url=live_database_url,
        )
        report = run_live_retrieval_case_set(
            context=context,
            cases_path=args.cases,
            seed_fixtures=args.seed_fixtures,
            case_limit=args.case_limit,
            report_path=args.report,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        if report.get("status") == "needs_review":
            raise SystemExit(1)
        return True
    return False
