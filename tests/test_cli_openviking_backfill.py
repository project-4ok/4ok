import json
from pathlib import Path

from fourok.cli import main
from fourok.governance import GovernedContext

FIXTURE = Path(__file__).parent.parent / "fixtures" / "openviking" / "messages_variants.jsonl"


def test_cli_backfills_openviking_messages_and_is_idempotent(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FOUR_OK_DATABASE_URL", "sqlite:///:memory:")
    state_path = tmp_path / "state.sqlite"

    def run_once() -> dict[str, object]:
        monkeypatch.setattr(
            "sys.argv",
            [
                "fourok",
                "backfill-openviking-messages",
                str(FIXTURE),
                "--state",
                str(state_path),
            ],
        )
        main()
        return json.loads(capsys.readouterr().out)

    first = run_once()
    context_after_first = GovernedContext(state_path)
    first_source_rows = context_after_first.source_records()
    first_retrieval_rows = context_after_first.retrieval_units()

    second = run_once()
    context_after_second = GovernedContext(state_path)

    assert first == {
        "input": str(FIXTURE),
        "record_count": 3,
        "source_refs": [
            "openviking:conversation:conv-product:session:sess-alpha:message:m-001",
            "openviking:conversation:conv-product:session:sess-alpha:message:m-002",
            "openviking:conversation:conv-support:session:sess-beta:message:m-003",
        ],
        "source_ref_count": 3,
        "source_systems": ["openviking"],
        "record_types": ["message"],
        "lifecycle_states": ["active"],
        "restricted_count": 0,
        "retrieval_unit_count": 3,
    }
    assert second == first
    assert context_after_second.source_records() == first_source_rows
    assert context_after_second.retrieval_units() == first_retrieval_rows
    assert [
        result.source_ref
        for result in context_after_second.search_context("Alpine Robotics checklist").results
    ] == ["openviking:conversation:conv-product:session:sess-alpha:message:m-001"]
    assert [
        row["source_ref"]
        for row in context_after_second.retrieval_units()
        if "Beacon Labs" in str(row["prepared_text"])
    ] == ["openviking:conversation:conv-support:session:sess-beta:message:m-003"]


def test_cli_backfill_openviking_explicit_database_url_overrides_state(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "unused.sqlite"
    database_path = tmp_path / "backfill.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "backfill-openviking-messages",
            str(FIXTURE),
            "--state",
            str(state_path),
            "--database-url",
            f"sqlite:///{database_path}",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    context = GovernedContext(state_path, database_url=f"sqlite:///{database_path}")

    assert output["retrieval_unit_count"] == 3
    assert len(context.retrieval_units()) == 3
    assert not state_path.exists()
