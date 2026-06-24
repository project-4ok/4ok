import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

RUNNER = Path("scripts/run_graphiti_context_eval.py")


def test_graphiti_runner_uses_lazy_graphiti_import_and_context_fixtures() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert (
        'DEFAULT_FIXTURE = Path("fixtures/context_substrate/source_snapshot_eval.json")' in source
    )
    assert (
        'DEFAULT_CASES = Path("fixtures/context_substrate/context_substrate_cases.json")' in source
    )
    assert "from graphiti_core import Graphiti" not in source.split("def _load_graphiti()")[0]
    assert "from graphiti_core import Graphiti" in source
    assert "from graphiti_core.nodes import EpisodeType" in source
    assert "graphiti_episodes_from_source_snapshot" in source
    assert "evaluate_graphiti_cases" in source
    assert 'uuid=str(episode["uuid"])' not in source


def test_graphiti_runner_dockerfile_keeps_graphiti_out_of_main_app() -> None:
    dockerfile = Path("docker/graphiti-runner.Dockerfile").read_text(encoding="utf-8")
    app_dockerfile = Path("docker/app.Dockerfile").read_text(encoding="utf-8")

    assert "COPY .reference" not in dockerfile
    assert "/app/.reference" not in dockerfile
    assert "--mount=type=cache,target=/root/.cache/uv" in dockerfile
    assert "uv sync --frozen --no-group dev --no-install-project" in dockerfile
    assert "ENV UV_HTTP_TIMEOUT=120" in dockerfile
    assert "graphiti-core==0.29.1" in dockerfile
    assert (
        'ENTRYPOINT ["/app/.venv/bin/python", "scripts/run_graphiti_context_eval.py"]' in dockerfile
    )
    assert "graphiti-core" not in app_dockerfile


def test_compose_does_not_expose_graphiti_runner_experiment_service() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "  graphiti-runner:" not in compose
    assert "  graphiti-neo4j:" not in compose
    assert "4ok-graphiti-runner" not in compose
    assert "docker/graphiti-runner.Dockerfile" not in compose
    assert "NEO4J_URI: bolt://graphiti-neo4j:7687" not in compose


def test_graphiti_eval_scores_permission_refs_from_fact_text() -> None:
    runner = _load_runner()

    class FakeGraphiti:
        async def search(self, *, group_ids, query, num_results):
            assert group_ids == ["gcb-fixture"]
            assert query == "renewal meeting"
            assert num_results == 3
            return [
                type(
                    "FakeResult",
                    (),
                    {
                        "fact": (
                            "source_ref: linear:issue:ABC-123 "
                            "entities: employee:email:olivia@example.com "
                            "permission_refs: linear:team:sales workflow:renewals"
                        )
                    },
                )()
            ]

    report = asyncio.run(
        runner.evaluate_graphiti_cases(
            FakeGraphiti(),
            cases=[
                {
                    "id": "governance",
                    "query": "renewal meeting",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                    "expected_entities": ["employee:email:olivia@example.com"],
                    "expected_permission_refs": [
                        "linear:team:sales",
                        "workflow:renewals",
                    ],
                }
            ],
            group_id="gcb-fixture",
            limit=3,
        )
    )

    assert report["summary"] == {
        "cases": 1,
        "passed": 1,
        "failed": 0,
        "top1_hits": 1,
        "top3_hits": 1,
        "provenance_cases": 1,
        "graphiti_only_passed": 1,
        "source_fallback_cases": 0,
        "source_fallback_items": 0,
    }
    assert report["cases"][0]["found_expected_permission_refs"] == [
        "linear:team:sales",
        "workflow:renewals",
    ]


def test_graphiti_eval_scores_source_refs_from_structured_episode_content() -> None:
    runner = _load_runner()

    class FakeGraphiti:
        async def search_(self, *, query, group_ids, config):
            assert query == "renewal meeting"
            assert group_ids == ["gcb-fixture"]
            assert config is None
            edge = type("FakeEdge", (), {"fact": "Robin Scharf moved the meeting."})()
            episode = type(
                "FakeEpisode",
                (),
                {
                    "name": "linear:issue:ABC-123",
                    "content": (
                        "source_ref: linear:issue:ABC-123\n"
                        "entities: employee:email:olivia@example.com\n"
                        "permission_refs: linear:team:sales workflow:renewals\n"
                    ),
                },
            )()
            return type("FakeResults", (), {"edges": [edge], "episodes": [episode]})()

    report = asyncio.run(
        runner.evaluate_graphiti_cases(
            FakeGraphiti(),
            cases=[
                {
                    "id": "structured",
                    "query": "renewal meeting",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                    "expected_entities": ["employee:email:olivia@example.com"],
                    "expected_permission_refs": ["linear:team:sales"],
                }
            ],
            group_id="gcb-fixture",
            limit=5,
        )
    )

    assert report["summary"]["passed"] == 1
    assert report["cases"][0]["found_expected_source_refs"] == ["linear:issue:ABC-123"]
    assert report["cases"][0]["found_expected_entities"] == ["employee:email:olivia@example.com"]
    assert report["cases"][0]["found_expected_permission_refs"] == ["linear:team:sales"]


def test_graphiti_eval_joins_edge_episode_uuids_to_source_provenance() -> None:
    runner = _load_runner()

    class FakeGraphiti:
        async def search_(self, *, query, group_ids, config):
            assert query == "renewal meeting"
            assert group_ids == ["gcb-fixture"]
            assert config is None
            edge = type(
                "FakeEdge",
                (),
                {
                    "fact": "Robin Scharf moved the meeting.",
                    "episodes": ["episode-abc-123"],
                },
            )()
            return type("FakeResults", (), {"edges": [edge], "episodes": []})()

    report = asyncio.run(
        runner.evaluate_graphiti_cases(
            FakeGraphiti(),
            cases=[
                {
                    "id": "edge_episode_lookup",
                    "query": "renewal meeting",
                    "expected_source_refs": ["linear:issue:ABC-123"],
                    "expected_entities": ["employee:email:olivia@example.com"],
                    "expected_permission_refs": ["linear:team:sales"],
                }
            ],
            group_id="gcb-fixture",
            limit=5,
            episode_lookup={
                "episode-abc-123": (
                    "source_ref: linear:issue:ABC-123\n"
                    "entities: employee:email:olivia@example.com\n"
                    "permission_refs: linear:team:sales workflow:renewals\n"
                )
            },
        )
    )

    assert report["summary"]["passed"] == 1
    assert report["cases"][0]["found_expected_source_refs"] == ["linear:issue:ABC-123"]
    assert report["cases"][0]["found_expected_entities"] == ["employee:email:olivia@example.com"]
    assert report["cases"][0]["found_expected_permission_refs"] == ["linear:team:sales"]


def test_graphiti_eval_can_use_source_record_fallback_for_unprovenanced_facts() -> None:
    runner = _load_runner()

    class FakeGraphiti:
        async def search_(self, *, query, group_ids, config):
            assert query == "Olivia Slack Linear Twenty employee"
            assert group_ids == ["gcb-fixture"]
            assert config is None
            edge = type(
                "FakeEdge",
                (),
                {
                    "fact": "Olivia Smith has the email olivia@example.com",
                    "episodes": [],
                },
            )()
            return type("FakeResults", (), {"edges": [edge], "episodes": []})()

    source_data = {
        "linear_users": [
            {
                "id": "linear-user-olivia",
                "display_name": "Olivia Smith",
                "email": "olivia@example.com",
            }
        ],
        "slack_users": [
            {
                "id": "UOLIVIA",
                "display_name": "Olivia Smith",
                "email": "olivia@example.com",
                "deleted": False,
                "is_bot": False,
            }
        ],
        "twenty_workspace_members": [
            {
                "id": "twenty-member-olivia",
                "display_name": "Olivia Smith",
                "email": "olivia@example.com",
            }
        ],
        "linear_issues": [],
        "linear_comments": [],
        "linear_teams": [],
        "linear_projects": [],
        "twenty_people": [],
        "twenty_companies": [],
    }

    report = asyncio.run(
        runner.evaluate_graphiti_cases(
            FakeGraphiti(),
            cases=[
                {
                    "id": "fallback",
                    "query": "Olivia Slack Linear Twenty employee",
                    "expected_source_refs": [
                        "linear:user:linear-user-olivia",
                        "slack:user:UOLIVIA",
                        "twenty:workspaceMember:twenty-member-olivia",
                    ],
                    "expected_entities": ["employee:email:olivia@example.com"],
                }
            ],
            group_id="gcb-fixture",
            limit=5,
            source_data=source_data,
        )
    )

    assert report["summary"]["passed"] == 1
    assert report["cases"][0]["found_expected_source_refs"] == [
        "linear:user:linear-user-olivia",
        "slack:user:UOLIVIA",
        "twenty:workspaceMember:twenty-member-olivia",
    ]
    assert report["cases"][0]["found_expected_entities"] == ["employee:email:olivia@example.com"]


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("graphiti_context_eval", RUNNER)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load Graphiti runner module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
