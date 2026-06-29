from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fourok.cli_parts.runtime_helpers import _database_url_from_args
from fourok.cli_parts.shared import DEFAULT_STATE, _principal_from_args
from fourok.etl.extract.context_snapshot import load_context_snapshot_source_records
from fourok.etl.extract.email_parser import load_email_dir_with_report
from fourok.governance import GovernedContext
from fourok.retrieval.clients import cli as retrieval_client
from fourok.retrieval.context_eval import evaluate_governed_context_retrieval
from fourok.runtime.cli import health_database_url
from fourok.runtime.operator_live import host_database_url
from fourok.secrets.env import load_dotenv

_EMBEDDING_ENV_KEYS = (
    "OPENAI_API_KEY",
    "FOUROK_EMBEDDING_PROVIDER",
    "FOUROK_EMBEDDING_DIMENSIONS",
    "FOUROK_OPENAI_EMBEDDING_MODEL",
    "FOUROK_OPENAI_EMBEDDING_URL",
)


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
        default=Path("tests/fixtures/emails"),
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
        "--token-budget",
        type=int,
        default=retrieval_client.DEFAULT_RETRIEVAL_TOKEN_BUDGET,
        help=argparse.SUPPRESS
        if public
        else "Estimated token budget for rendered retrieval context.",
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
    ask_parser.add_argument("--emails", type=Path, default=Path("tests/fixtures/emails"))
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
        default=Path("tests/fixtures/retrieval_eval/live_retrieval_case_set.json"),
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

    retrieval_eval_parser = subparsers.add_parser(
        "eval-retrieval",
        help="Run the local golden-query retrieval/evidence evaluation.",
    )
    retrieval_eval_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("tests/fixtures/context_substrate/evidence_baseline_cases.json"),
    )
    retrieval_eval_parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/context_substrate/source_snapshot_eval.json"),
        help="Fixture JSON containing source records and source catalog data.",
    )
    retrieval_eval_parser.add_argument("--limit", type=int, default=5)


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
        database_url = _retrieval_database_url(args, database_url)
        _load_embedding_env_for_retrieve()
        retrievers = tuple(item.strip() for item in str(args.retrievers).split(",") if item.strip())
        try:
            if args.format == "json":
                response = retrieval_client.retrieve_augmentation(
                    args.query,
                    token_budget=args.token_budget,
                    candidate_limit=args.candidate_limit,
                    retrievers=retrievers,
                    state=args.state,
                    database_url=database_url,
                )
                print(json.dumps(response, indent=2))
            else:
                block = retrieval_client.retrieve_block(
                    args.query,
                    token_budget=args.token_budget,
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

    if args.command == "eval-retrieval":
        try:
            records = load_context_snapshot_source_records(args.fixture)
            cases = _load_retrieval_eval_cases(args.cases)
            report = evaluate_governed_context_retrieval(records, cases, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"substrate": "governed_context", **report}, indent=2))
        return True

    return False


def _load_retrieval_eval_cases(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read retrieval eval cases: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid retrieval eval cases JSON: {path}") from exc
    if not isinstance(data, list):
        raise ValueError("retrieval eval cases must be a JSON list")
    cases = [item for item in data if isinstance(item, dict)]
    if len(cases) != len(data):
        raise ValueError("retrieval eval cases must contain only objects")
    for index, case in enumerate(cases, start=1):
        if not isinstance(case.get("query"), str) or not case.get("query"):
            raise ValueError(f"retrieval eval case {index} requires query")
    return cases


def _retrieval_database_url(args: argparse.Namespace, database_url: str | None) -> str | None:
    if not database_url:
        if _running_in_container():
            return None
        return health_database_url(
            state=getattr(args, "state", DEFAULT_STATE),
            state_explicit=getattr(args, "state_explicit", False),
            explicit_database_url=None,
        )
    if _running_in_container():
        return database_url
    if getattr(args, "state", DEFAULT_STATE) != DEFAULT_STATE:
        return database_url
    return host_database_url(database_url)


def _load_embedding_env_for_retrieve() -> None:
    dotenv_path = Path(os.environ.get("FOUROK_DOTENV_PATH") or ".env")
    dotenv_values = load_dotenv(dotenv_path)
    for key in _EMBEDDING_ENV_KEYS:
        value = dotenv_values.get(key)
        if value and not os.environ.get(key):
            os.environ[key] = value


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
