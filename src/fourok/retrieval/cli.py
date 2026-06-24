from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fourok.cli_parts.runtime_helpers import _database_url_from_args
from fourok.cli_parts.shared import DEFAULT_STATE, _principal_from_args
from fourok.etl.extract.email_parser import load_email_dir_with_report
from fourok.governance import GovernedContext
from fourok.retrieval.clients import cli as retrieval_client
from fourok.runtime.operator_live import host_database_url


def add_search_commands(subparsers, *, public: bool = False) -> None:
    search_parser = subparsers.add_parser(
        "search",
        help="Search local email fixture regression data.",
        description="Search local email fixture regression data.",
    )
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--emails",
        type=Path,
        default=Path("fixtures/emails"),
        help="Test-only directory containing fixture .eml files.",
    )
    search_parser.add_argument("--limit", type=int, default=5)
    search_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help="State database for governed search.",
    )
    search_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
        help="SQLAlchemy database URL. Defaults to SQLite --state when unset.",
    )

    search_state_parser = subparsers.add_parser(
        "search-state",
        help="Search existing governed state without loading fixture emails.",
    )
    search_state_parser.add_argument("query")
    search_state_parser.add_argument("--limit", type=int, default=5)
    search_state_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    search_state_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
        help="SQLAlchemy database URL. Defaults to SQLite --state when unset.",
    )
    search_state_parser.add_argument("--human-id", default="local-human")
    search_state_parser.add_argument("--agent-id", default="local-agent")
    search_state_parser.add_argument("--role", action="append", default=["operator"])

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Build an LLM-ready retrieval augmentation block from governed state.",
        description="Build an LLM-ready retrieval augmentation block from governed state.",
    )
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument(
        "--candidate-limit",
        type=int,
        default=40,
        help=argparse.SUPPRESS if public else None,
    )
    retrieve_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help=argparse.SUPPRESS if public else None,
    )
    retrieve_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
        help=argparse.SUPPRESS
        if public
        else "SQLAlchemy database URL. Defaults to SQLite --state when unset.",
    )
    retrieve_parser.add_argument(
        "--format",
        choices=["block", "json"],
        default="block",
        help=argparse.SUPPRESS
        if public
        else "Output format. The default block format is designed for LLM prompt augmentation.",
    )
    retrieve_parser.add_argument(
        "--json",
        dest="format",
        action="store_const",
        const="json",
        help="Print machine-readable JSON.",
    )
    retrieve_parser.add_argument(
        "--retrievers",
        default="keyword,vector",
        help=argparse.SUPPRESS if public else "Comma-separated retrievers to use: keyword,vector.",
    )

    ask_parser = subparsers.add_parser(
        "ask",
        help="Run the human-with-agent governed context workflow.",
    )
    ask_parser.add_argument("query")
    ask_parser.add_argument("--emails", type=Path, default=Path("fixtures/emails"))
    ask_parser.add_argument("--limit", type=int, default=5)
    ask_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ask_parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL"))
    ask_parser.add_argument("--human-id", default="local-human")
    ask_parser.add_argument("--agent-id", default="local-agent")
    ask_parser.add_argument("--role", action="append", default=["operator"])

    live_retrieval_case_set_parser = subparsers.add_parser(
        "live-retrieval-case-set",
        help="Run a repeatable retrieval case-set for live surface smoke checks.",
    )
    live_retrieval_case_set_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/retrieval_eval/live_retrieval_case_set.json"),
    )
    live_retrieval_case_set_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
    )
    live_retrieval_case_set_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
    )
    live_retrieval_case_set_parser.add_argument("--seed-fixtures", action="store_true")
    live_retrieval_case_set_parser.add_argument("--case-limit", type=int, default=5)
    live_retrieval_case_set_parser.add_argument(
        "--report",
        type=Path,
        default=Path(".local/codex-runs/live-retrieval-case-set/report.md"),
    )


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
