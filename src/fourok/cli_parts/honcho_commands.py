from __future__ import annotations

import argparse
import json

from fourok.cli_parts import honcho_helpers as helpers
from fourok.etl.extract.context_snapshot import (
    context_snapshot_source_records,
    load_context_snapshot_source_records,
)
from fourok.retrieval.context_eval import evaluate_governed_context_retrieval


def dispatch_honcho(args: argparse.Namespace) -> bool:
    if args.command == "honcho-sync":
        helpers._ensure_honcho_experiment_symbols()
        helpers._ensure_honcho_state_symbol()
        data = helpers._honcho_sync_data_from_args(args)
        planning_state = helpers._honcho_planning_state_from_args(args)
        plan = helpers.build_honcho_sync_plan(
            data,
            existing_employees=planning_state.employee_catalog() if planning_state else None,
        )
        if args.write:
            helpers._ensure_honcho_client_symbol()
            helpers._ensure_honcho_sync_symbol()
            state_path = helpers._honcho_sync_state_path(args)
            state = planning_state or helpers.HonchoSyncState.load(state_path)
            client = helpers.HonchoHttpClient(
                base_url=args.honcho_url,
                workspace_id=args.workspace_id,
                api_key=args.api_key,
            )
            try:
                report = helpers.execute_honcho_sync(plan, state=state, client=client)
            except OSError as exc:
                raise SystemExit(f"Honcho write failed: {exc}") from exc
            print(json.dumps(report, indent=2))
            return True
        output = (
            {"mode": "dry-run", "summary": plan.summary}
            if args.summary_only
            else plan.to_dry_run_dict()
        )
        if args.state is not None:
            try:
                state = helpers.HonchoSyncState.load(args.state)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            output["idempotency"] = state.classify_message_source_refs(
                [
                    {
                        "source_ref": message.metadata.get("source_ref"),
                        "source_updated_at": message.metadata.get("source_updated_at"),
                    }
                    for message in plan.messages
                    if message.metadata.get("source_ref")
                ]
            )
        print(json.dumps(output, indent=2))
        return True

    if args.command == "honcho-receipt":
        helpers._ensure_honcho_state_symbol()
        try:
            state = helpers.HonchoSyncState.load(args.state)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            json.dumps(
                {
                    "source_ref": args.source_ref,
                    "receipt": state.source_receipt(args.source_ref),
                },
                indent=2,
            )
        )
        return True

    if args.command == "honcho-smoke":
        helpers._ensure_honcho_client_symbol()
        helpers._ensure_honcho_experiment_symbols()
        client = helpers.HonchoHttpClient(
            base_url=args.honcho_url,
            workspace_id=args.workspace_id,
            api_key=args.api_key,
        )
        try:
            health = client.health()
        except OSError as exc:
            output = {
                "status": "skipped",
                "honcho_url": args.honcho_url,
                "reason": str(exc),
            }
            print(json.dumps(output, indent=2))
            if args.require:
                raise SystemExit(1) from exc
            return True

        try:
            data = helpers.load_honcho_fixture(args.fixture)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        plan = helpers.build_honcho_sync_plan(data)
        if not plan.messages:
            raise SystemExit("Honcho smoke fixture produced no messages")
        smoke_message = plan.messages[0]
        write_response = client.add_message(smoke_message)
        readback = client.list_messages(smoke_message.session)
        smoke_source_ref = smoke_message.metadata.get("source_ref")
        source_ref_found = helpers._honcho_readback_has_source_ref(readback, smoke_source_ref)
        search_probe = helpers._honcho_smoke_search_probe(client, smoke_message, smoke_source_ref)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "honcho_url": args.honcho_url,
                    "workspace_id": args.workspace_id,
                    "health": health,
                    "written_messages": 1,
                    "write_response": write_response,
                    "source_ref_readback": {
                        "source_ref": smoke_source_ref,
                        "found": source_ref_found,
                    },
                    "source_ref_search": search_probe,
                    "readback": readback,
                },
                indent=2,
            )
        )
        if args.require and not source_ref_found:
            raise SystemExit(1)
        return True

    if args.command == "honcho-eval":
        helpers._ensure_honcho_client_symbol()
        client = helpers.HonchoHttpClient(
            base_url=args.honcho_url,
            workspace_id=args.workspace_id,
            api_key=args.api_key,
        )
        try:
            cases = helpers._load_honcho_eval_cases(args.cases)
            report = helpers._evaluate_honcho_retrieval(
                client=client,
                cases=cases,
                limit=args.limit,
            )
        except (OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(report, indent=2))
        return True

    if args.command == "eval-retrieval":
        try:
            if args.live_sources:
                args.fixture = None
                data = helpers._honcho_sync_data_from_args(args)
                records = context_snapshot_source_records(data)
            else:
                records = load_context_snapshot_source_records(args.fixture)
            cases = helpers._load_honcho_eval_cases(args.cases)
            report = evaluate_governed_context_retrieval(records, cases, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        report = {"substrate": "governed_context", **report}
        print(json.dumps(report, indent=2))
        return True

    if args.command == "evidence-baseline-eval":
        helpers._ensure_evidence_baseline_symbol()
        try:
            data = helpers._honcho_sync_data_from_args(args)
            cases = helpers._load_honcho_eval_cases(args.cases)
            report = helpers.evaluate_evidence_baseline(data, cases, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        report = {"substrate": "custom_evidence_baseline", **report}
        print(json.dumps(report, indent=2))
        return True

    if args.command == "honcho-preflight":
        helpers._ensure_honcho_preflight_symbols()
        report = (
            helpers.source_connection_preflight(
                helpers.effective_env(),
                sources=helpers._parse_honcho_sources(args.sources),
            )
            if args.check_sources
            else helpers.source_secret_preflight(helpers.effective_env())
        )
        print(json.dumps(report, indent=2))
        return True

    return False
