from __future__ import annotations

import argparse
import json

from fourok.cli_parts.runtime_helpers import _database_url_from_args
from fourok.cli_parts.shared import DEFAULT_STATE, _principal_from_args
from fourok.etl.extract.email_parser import load_email_dir_with_report
from fourok.governance import GovernedContext
from fourok.retrieval.clients import cli as retrieval_client
from fourok.runtime.operator_live import host_database_url


def dispatch_search_commands(args: argparse.Namespace) -> bool:
    database_url = _database_url_from_args(args)
    if args.command == "search":
        load_report = load_email_dir_with_report(args.emails)
        response = retrieval_client.search_fixture(
            messages=load_report.messages,
            query=args.query,
            limit=args.limit,
            state=args.state,
            database_url=database_url,
        )
        print(
            json.dumps(
                {
                    "query": args.query,
                    "load": {
                        "loaded": len(load_report.messages),
                        "skipped": len(load_report.skipped),
                        "skipped_files": load_report.skipped,
                    },
                    "results": response["results"],
                },
                indent=2,
            )
        )
        return True

    if args.command == "search-state":
        response = retrieval_client.search_state(
            args.query,
            limit=args.limit,
            principal=_principal_from_args(args),
            state=args.state,
            database_url=database_url,
            context_factory=GovernedContext,
        )
        print(
            json.dumps(
                {
                    "query": args.query,
                    "load": {"loaded": 0, "source": "existing_state"},
                    "results": response["results"],
                    "summary": response["summary"],
                    "result_candidates": response["result_candidates"],
                    "evidence_items": response["evidence_items"],
                    "primary_objects": response["primary_objects"],
                    "related_objects": response["related_objects"],
                    "related_object_groups": response["related_object_groups"],
                    "entities": response["entities"],
                    "unresolved_candidates": response["unresolved_candidates"],
                    "limitations": response["limitations"],
                    "audit_ref": response["audit_ref"],
                },
                indent=2,
            )
        )
        return True

    if args.command == "retrieve":
        retrievers = tuple(item.strip() for item in str(args.retrievers).split(",") if item.strip())
        try:
            if args.format == "json":
                response = retrieval_client.retrieve_augmentation(
                    args.query,
                    candidate_limit=args.candidate_limit,
                    retrievers=retrievers,
                    state=args.state,
                    database_url=database_url,
                )
                print(json.dumps(response, indent=2))
            else:
                block = retrieval_client.retrieve_block(
                    args.query,
                    candidate_limit=args.candidate_limit,
                    retrievers=retrievers,
                    state=args.state,
                    database_url=database_url,
                )
                print(block, end="")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return True

    if args.command == "ask":
        load_report = load_email_dir_with_report(args.emails)
        response = retrieval_client.ask_fixture(
            messages=load_report.messages,
            query=args.query,
            principal=_principal_from_args(args),
            limit=args.limit,
            state=args.state,
            database_url=database_url,
        )
        print(
            json.dumps(
                {
                    **response,
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
        report = retrieval_client.run_live_retrieval_case_set(
            state=args.state,
            database_url=live_database_url,
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
