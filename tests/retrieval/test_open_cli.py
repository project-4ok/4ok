from __future__ import annotations

import json

from fourok.cli import main
from fourok.cli_parts.shared import DEFAULT_STATE


def test_open_cli_uses_retrieval_api(capsys, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_open(source_ref: str, **kwargs) -> dict[str, object]:
        observed["source_ref"] = source_ref
        observed.update(kwargs)
        return {
            "status": "ok",
            "source_ref": source_ref,
            "title": "Refund escalation",
            "text": "Expanded source context.",
            "inspection_event_id": "retrieval-inspection:def",
        }

    monkeypatch.setattr(
        "fourok.retrieval.cli.retrieval_client.open",
        fake_open,
    )
    monkeypatch.delenv("FOUROK_DATABASE_URL", raising=False)
    monkeypatch.setattr("fourok.retrieval.cli.health_database_url", lambda **_kwargs: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "open",
            "linear:issue:1",
            "--retrieval-event-id",
            "retrieval-query:abc",
            "--rank",
            "2",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "source_ref": "linear:issue:1",
        "title": "Refund escalation",
        "text": "Expanded source context.",
        "inspection_event_id": "retrieval-inspection:def",
    }
    assert observed == {
        "source_ref": "linear:issue:1",
        "retrieval_event_id": "retrieval-query:abc",
        "rank": 2,
        "state": DEFAULT_STATE,
        "database_url": None,
    }
