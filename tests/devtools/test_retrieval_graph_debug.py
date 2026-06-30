from __future__ import annotations

import json
from pathlib import Path

from fourok.devtools.retrieval_graph import (
    build_retrieval_debug_graph,
    retrieval_analysis_dashboard_html,
    write_retrieval_debug_artifacts,
)


def test_retrieval_debug_graph_shows_final_wide_direct_and_db_edges() -> None:
    final = {
        "status": "ok",
        "token_budget": 300,
        "estimated_tokens": 240,
        "candidate_count": 4,
        "results": [
            {
                "source_ref": "linear:user:olivia",
                "source_system": "linear",
                "record_type": "person",
                "title": "olivia.allen@4ok.tech",
                "snippet": "employee",
                "score": 9.1,
                "retrievers": ["keyword"],
                "rerank_reasons": [],
            }
        ],
        "limitations": ["Searched keyword and vector candidates."],
    }
    wide = {
        "status": "ok",
        "token_budget": 10000,
        "estimated_tokens": 800,
        "results": [
            *final["results"],
            {
                "source_ref": "linear:issue:OPS-1",
                "source_system": "linear",
                "record_type": "work_item",
                "title": "Access for Olivia",
                "snippet": "Olivia needs dashboard access.",
                "score": 7.0,
                "retrievers": ["keyword", "direct-link"],
                "rerank_reasons": ["direct context for linear:user:olivia"],
            },
            {
                "source_ref": "twenty:company:4ok",
                "source_system": "twenty",
                "record_type": "organization",
                "title": "4ok",
                "snippet": "",
                "score": 3.0,
                "retrievers": ["vector"],
                "rerank_reasons": [],
            },
        ],
    }

    graph = build_retrieval_debug_graph(
        query="olivia",
        final_retrieval=final,
        wide_retrieval=wide,
        entity_links=[
            {
                "source_ref": "linear:issue:OPS-1",
                "object_ref": "linear:user:olivia",
                "relationship_type": "assignee",
                "reason": "linear assignee id",
            },
            {
                "source_ref": "linear:user:olivia",
                "object_ref": "identity:email:olivia.allen@4ok.tech",
                "relationship_type": "email_identity",
                "reason": "identity ref",
            },
        ],
    )

    nodes = {node["id"]: node for node in graph["nodes"]}
    links = {(link["source"], link["target"], link["rel"]): link for link in graph["links"]}

    assert nodes["linear:user:olivia"]["final_selected"] is True
    assert nodes["linear:user:olivia"]["label"] == "Olivia Allen"
    assert nodes["linear:user:olivia"]["title"] == "olivia.allen@4ok.tech"
    assert "weak" not in nodes["linear:user:olivia"]
    assert "flags" not in nodes["linear:user:olivia"]
    assert nodes["linear:issue:OPS-1"]["stage"] == "candidate_one_hop_not_selected"
    assert nodes["twenty:company:4ok"]["stage"] == "candidate_not_selected"
    assert nodes["identity:email:olivia.allen@4ok.tech"]["type"] == "entity"
    assert links[("query:olivia", "linear:user:olivia", "keyword_candidate")]
    assert links[("query:olivia", "twenty:company:4ok", "vector_candidate")]
    assert links[("linear:user:olivia", "linear:issue:OPS-1", "direct_context_for")]
    assert links[("linear:issue:OPS-1", "linear:user:olivia", "entity_link")][
        "relationship_type"
    ] == "assignee"
    assert links[
        ("linear:user:olivia", "identity:email:olivia.allen@4ok.tech", "entity_link")
    ]["relationship_type"] == "email_identity"
    assert graph["stats"]["final_result_count"] == 1
    assert graph["stats"]["wide_result_count"] == 3
    assert graph["stats"]["edge_counts"]["direct_context_for"] == 1
    assert graph["stats"]["edge_counts"]["entity_link"] == 2


def test_write_retrieval_debug_artifacts_creates_json_and_html(tmp_path: Path) -> None:
    graph = build_retrieval_debug_graph(
        query="olivia allen",
        final_retrieval={"results": [], "limitations": []},
        wide_retrieval={"results": []},
        entity_links=[],
    )

    report = write_retrieval_debug_artifacts(
        query="olivia allen",
        graph=graph,
        output_dir=tmp_path,
        serve_url_base="http://127.0.0.1:8765",
    )

    graph_json = Path(str(report["graph_json"]))
    html_path = Path(str(report["html"]))
    assert graph_json.exists()
    assert html_path.exists()
    assert json.loads(graph_json.read_text(encoding="utf-8"))["stats"]["query"] == "olivia allen"
    html = html_path.read_text(encoding="utf-8")
    assert "Retrieval analysis dashboard" in html
    assert "queryInput" in html
    assert "id=\"showLabels\" type=\"checkbox\" checked" in html
    assert "id=\"showEdgeLabels\" type=\"checkbox\"" in html
    assert "id=\"showEdgeLabels\" type=\"checkbox\" checked" not in html
    assert "weak/noisy" not in html
    assert "#f3f3f2" in html
    assert "#1800ad" in html
    assert "#f0353b" in html
    assert "#26211e" in html
    assert "Akzidenz-Grotesk" in html
    assert "stroke-dasharray" not in html
    assert "dashed" not in html.casefold()
    assert "Retrieval focus" in html
    assert "Context/entity graph" in html
    assert "Other candidates" in html
    assert "Linear/source candidates" not in html
    assert "DB entity links" not in html
    assert "#0f766e" not in html
    assert "#7c3aed" not in html
    assert "#8f8780" not in html
    assert "/api/retrieval-graph?query=" in html
    assert "d3@7" in html
    assert report["url"] == "http://127.0.0.1:8765/olivia-allen.graph.html"


def test_retrieval_analysis_dashboard_starts_without_hardcoded_query() -> None:
    html = retrieval_analysis_dashboard_html()

    assert "Retrieval analysis dashboard" in html
    assert "placeholder=\"Enter retrieval query…\"" in html
    assert "value=\"\"" in html
    assert "olivia" not in html.casefold()
