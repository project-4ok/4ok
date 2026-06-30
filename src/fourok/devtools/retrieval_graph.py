from __future__ import annotations

# ruff: noqa: E501
import html
import json
import re
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine

from fourok.retrieval.api import RetrievalAPI
from fourok.runtime.operator_live import host_database_url

DEFAULT_OUTPUT_DIR = Path(".local/retrieval-graph-debug")
DEFAULT_SERVE_URL_BASE = "http://127.0.0.1:8765"
DIRECT_CONTEXT_RE = re.compile(r"^direct (?:context for|link from) (?P<source_ref>.+)$")


def build_retrieval_debug_graph(
    *,
    query: str,
    final_retrieval: dict[str, Any],
    wide_retrieval: dict[str, Any],
    entity_links: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a force-graph payload that separates retrieval reasons from DB KG links."""

    final_results = _result_list(final_retrieval)
    wide_results = _dedupe_results([*_result_list(wide_retrieval), *final_results])
    final_refs = {str(result["source_ref"]) for result in final_results if result.get("source_ref")}
    query_id = f"query:{query}"

    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str], dict[str, Any]] = {}

    def add_node(node_id: str, **attrs: Any) -> None:
        node = nodes.setdefault(node_id, {"id": node_id})
        node.update({key: value for key, value in attrs.items() if value is not None})

    def add_link(source: str, target: str, rel: str, **attrs: Any) -> None:
        if not source or not target or source == target:
            return
        key = _link_key(source, target)
        weight = attrs.pop("weight", 1)
        link = links.setdefault(
            key,
            {"source": source, "target": target, "rel": rel, "rels": [], "weight": weight},
        )
        link["weight"] = max(float(link.get("weight", 1)), float(weight))
        if rel not in link["rels"]:
            link["rels"].append(rel)
        if rel == "entity_link":
            # Prefer the DB edge as the visible edge when a one-hop retrieval edge and
            # an entity_link connect the same pair. Otherwise D3 draws two straight
            # lines on top of each other and it looks like a duplicated edge.
            link.update({"source": source, "target": target, "rel": rel})
        relationship_type = str(attrs.pop("relationship_type", "") or "")
        if relationship_type:
            relationship_types = link.setdefault("relationship_types", [])
            if relationship_type not in relationship_types:
                relationship_types.append(relationship_type)
            link["relationship_type"] = ", ".join(relationship_types)
        for key_name, value in attrs.items():
            if value is not None:
                link[key_name] = value

    add_node(
        query_id,
        label=f"query: {query}",
        type="query",
        group="query",
        stage="query",
        final_selected=True,
        selected=True,
        order=0,
    )

    final_order = {
        str(result["source_ref"]): order
        for order, result in enumerate(final_results, start=1)
        if result.get("source_ref")
    }
    candidate_order = {
        str(result["source_ref"]): order
        for order, result in enumerate(wide_results, start=1)
        if result.get("source_ref")
    }
    direct_edges: list[dict[str, str]] = []

    for result in wide_results:
        source_ref = str(result.get("source_ref") or "")
        if not source_ref:
            continue
        retrievers = [str(item) for item in result.get("retrievers", [])]
        reasons = [str(item) for item in result.get("rerank_reasons", [])]
        is_final = source_ref in final_refs
        direct_source = _direct_context_source(reasons)
        add_node(
            source_ref,
            label=_short_title(_result_label(result, source_ref)),
            title=result.get("title", ""),
            source_ref=source_ref,
            type=result.get("record_type") or "source",
            group=result.get("source_system") or _source_group(source_ref),
            stage=_stage(retrievers, is_final=is_final, direct_source=direct_source),
            selected=True,
            final_selected=is_final,
            order=final_order.get(source_ref),
            candidate_order=candidate_order.get(source_ref),
            score=result.get("score"),
            retrievers=retrievers,
            rerank_reasons=reasons,
            snippet=str(result.get("snippet") or "")[:900],
            occurred_at=result.get("occurred_at", ""),
        )

        if direct_source:
            add_node(
                direct_source,
                label=nodes.get(direct_source, {}).get("label") or _short_title(direct_source),
                source_ref=direct_source,
                type="source",
                group=_source_group(direct_source),
                stage="expanded_from_not_returned",
                selected=direct_source in candidate_order,
                final_selected=direct_source in final_refs,
            )
            add_link(direct_source, source_ref, "direct_context_for", weight=3)
            direct_edges.append({"from": direct_source, "to": source_ref, "rel": "direct_context_for"})

        for retriever in retrievers:
            if retriever in {"keyword", "vector"}:
                add_link(
                    query_id,
                    source_ref,
                    f"{retriever}_candidate",
                    weight=3 if retriever == "keyword" else 1,
                )

    entity_edge_rows = []
    for row in entity_links:
        source_ref = str(row.get("source_ref") or "")
        object_ref = str(row.get("object_ref") or "")
        if not source_ref or not object_ref:
            continue
        if source_ref not in nodes:
            continue
        entity_edge_rows.append(row)
        add_node(
            object_ref,
            label=nodes.get(object_ref, {}).get("label") or _short_title(_entity_label(row)),
            source_ref=object_ref,
            type="entity" if object_ref not in nodes else nodes[object_ref].get("type"),
            group=nodes.get(object_ref, {}).get("group") or _source_group(object_ref) or "entity",
            stage=nodes.get(object_ref, {}).get("stage") or "db_entity_link",
            selected=nodes.get(object_ref, {}).get("selected", False),
            final_selected=nodes.get(object_ref, {}).get("final_selected", False),
        )
        add_link(
            source_ref,
            object_ref,
            "entity_link",
            weight=2,
            relationship_type=str(row.get("relationship_type") or ""),
            reason=str(row.get("reason") or ""),
        )

    stats = {
        "query": query,
        "pipeline": (
            "keyword/vector candidates -> one-hop direct-link expansion -> rerank/diversify "
            "-> token-budget selection"
        ),
        "note": (
            "Shows final selected results plus wider ranked candidates outside the normal "
            "token budget. Retrieval reason edges and DB entity_links are separate edge types."
        ),
        "final_result_count": len(final_results),
        "wide_result_count": len(wide_results),
        "candidate_count_after_expansion": final_retrieval.get("candidate_count"),
        "final_estimated_tokens": final_retrieval.get("estimated_tokens"),
        "final_token_budget": final_retrieval.get("token_budget"),
        "wide_estimated_tokens": wide_retrieval.get("estimated_tokens"),
        "wide_token_budget": wide_retrieval.get("token_budget"),
        "node_count": len(nodes),
        "edge_count": len(links),
        "edge_counts": dict(
            Counter(rel for link in links.values() for rel in link.get("rels", [link["rel"]]))
        ),
        "entity_link_relationship_counts": dict(
            Counter(str(row.get("relationship_type") or "") for row in entity_edge_rows)
        ),
        "direct_context_edge_count": len(direct_edges),
        "limitations": final_retrieval.get("limitations", []),
    }
    return {"stats": stats, "nodes": list(nodes.values()), "links": list(links.values())}


def retrieval_debug_graph_report(
    *,
    query: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    final_token_budget: int = 2000,
    wide_token_budget: int = 20000,
    candidate_limit: int = 80,
    serve_url_base: str = DEFAULT_SERVE_URL_BASE,
) -> dict[str, Any]:
    host_url = host_database_url(database_url or "") or None
    api = RetrievalAPI(state=state, database_url=host_url, config=config)
    final_retrieval = api.retrieve_augmentation(
        query,
        token_budget=final_token_budget,
        candidate_limit=candidate_limit,
    )
    wide_retrieval = api.retrieve_augmentation(
        query,
        token_budget=wide_token_budget,
        candidate_limit=candidate_limit,
    )
    source_refs = _source_refs(wide_retrieval) | _source_refs(final_retrieval)
    links = query_entity_links_for_graph(database_url=host_url, source_refs=source_refs)
    graph = build_retrieval_debug_graph(
        query=query,
        final_retrieval=final_retrieval,
        wide_retrieval=wide_retrieval,
        entity_links=links,
    )
    report = write_retrieval_debug_artifacts(
        query=query,
        graph=graph,
        output_dir=output_dir,
        serve_url_base=serve_url_base,
    )
    return {**report, "stats": graph["stats"]}


def query_entity_links_for_graph(
    *,
    database_url: str | None,
    source_refs: set[str],
) -> list[dict[str, Any]]:
    if not database_url or not source_refs:
        return []
    engine = create_engine(host_database_url(database_url))
    return query_entity_links_for_graph_engine(engine, source_refs=source_refs)


def query_entity_links_for_graph_engine(engine: Engine, *, source_refs: set[str]) -> list[dict[str, Any]]:
    if not source_refs:
        return []
    statement = text(
        """
        SELECT source_ref, object_ref, relationship_type, reason
        FROM entity_links
        WHERE source_ref IN :source_refs
          AND status IN ('linked', 'accepted')
        ORDER BY source_ref, object_ref, relationship_type
        """
    ).bindparams(bindparam("source_refs", expanding=True))
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                statement, {"source_refs": tuple(sorted(source_refs))}
            ).mappings()
        ]


def write_retrieval_debug_artifacts(
    *,
    query: str,
    graph: dict[str, Any],
    output_dir: Path,
    serve_url_base: str = DEFAULT_SERVE_URL_BASE,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(query)
    graph_json = output_dir / f"{slug}.graph.json"
    html_path = output_dir / f"{slug}.graph.html"
    graph_json.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    html_path.write_text(_html(query, graph), encoding="utf-8")
    return {
        "graph_json": str(graph_json),
        "html": str(html_path),
        "url": f"{serve_url_base.rstrip('/')}/{html_path.name}",
        "serve_command": f"python3 -m http.server 8765 --directory {output_dir}",
    }



def serve_retrieval_analysis_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    final_token_budget: int = 2000,
    wide_token_budget: int = 20000,
    candidate_limit: int = 80,
) -> None:
    serve_url_base = f"http://{host}:{port}"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/dashboard.html"}:
                self._send_html(retrieval_analysis_dashboard_html())
                return
            if parsed.path == "/api/retrieval-graph":
                params = parse_qs(parsed.query)
                query = (params.get("query") or [""])[0].strip()
                if not query:
                    self._send_json({"status": "error", "error": "query is required"}, status=400)
                    return
                try:
                    report = retrieval_debug_graph_report(
                        query=query,
                        output_dir=output_dir,
                        state=state,
                        database_url=database_url,
                        config=config,
                        final_token_budget=final_token_budget,
                        wide_token_budget=wide_token_budget,
                        candidate_limit=candidate_limit,
                        serve_url_base=serve_url_base,
                    )
                    graph = json.loads(Path(str(report["graph_json"])).read_text(encoding="utf-8"))
                    self._send_json({"status": "ok", "report": report, "graph": graph})
                except Exception as exc:  # pragma: no cover - depends on local runtime state.
                    self._send_json({"status": "error", "error": str(exc)}, status=500)
                return
            self._send_json({"status": "error", "error": "not found"}, status=404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, body: dict[str, Any], *, status: int = 200) -> None:
            payload = json.dumps(body, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"retrieval analysis dashboard: {serve_url_base}/dashboard.html")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def retrieval_analysis_dashboard_html(
    *, query: str = "", graph: dict[str, Any] | None = None
) -> str:
    empty_graph = {
        "stats": {
            "query": query,
            "note": "Enter a query to build a retrieval analysis graph.",
            "node_count": 0,
            "edge_count": 0,
        },
        "nodes": [],
        "links": [],
    }
    return _html(query, graph or empty_graph)


def _result_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    return list(results) if isinstance(results, list) else []


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for result in results:
        source_ref = str(result.get("source_ref") or "")
        key = f"{source_ref}:{result.get('unit_index', 0)}"
        if not source_ref or key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _source_refs(payload: dict[str, Any]) -> set[str]:
    return {str(result["source_ref"]) for result in _result_list(payload) if result.get("source_ref")}


def _link_key(source: str, target: str) -> tuple[str, str]:
    if source.startswith("query:") or target.startswith("query:"):
        return (source, target)
    first, second = sorted((source, target))
    return (first, second)


def _stage(retrievers: list[str], *, is_final: bool, direct_source: str) -> str:
    if is_final:
        return "final_selected_direct_link" if direct_source else "final_selected"
    if direct_source or "direct-link" in retrievers or "direct-context" in retrievers:
        return "candidate_one_hop_not_selected"
    return "candidate_not_selected"


def _direct_context_source(reasons: list[str]) -> str:
    for reason in reasons:
        match = DIRECT_CONTEXT_RE.match(reason)
        if match:
            return match.group("source_ref")
    return ""


def _entity_label(row: dict[str, Any]) -> str:
    object_ref = str(row.get("object_ref") or "")
    if object_ref.startswith("identity:"):
        return object_ref.removeprefix("identity:")
    return object_ref


def _result_label(result: dict[str, Any], source_ref: str) -> str:
    title = str(result.get("title") or "").strip()
    if result.get("record_type") == "person" and _looks_like_email(title):
        return _name_from_email(title)
    return title or source_ref


def _looks_like_email(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value))


def _name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    words = [word for word in re.split(r"[._+-]+", local_part) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words) or email


def _source_group(source_ref: str) -> str:
    if ":" in source_ref:
        return source_ref.split(":", 1)[0]
    return "source"


def _short_title(value: str, limit: int = 38) -> str:
    text_value = " ".join(str(value).split())
    return text_value if len(text_value) <= limit else text_value[: limit - 1].rstrip() + "…"


def _slug(query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.casefold()).strip("-")
    return slug or "retrieval"


def _html(query: str, graph: dict[str, Any]) -> str:
    data = json.dumps(graph)
    escaped_query = html.escape(query)
    escaped_stats = html.escape(json.dumps(graph["stats"], indent=2))
    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>fourok retrieval analysis dashboard</title>
<script src=\"https://cdn.jsdelivr.net/npm/d3@7\"></script>
<style>
  :root {{
    color-scheme: light;
    --primary: #f3f3f2;
    --accent-1: #1800ad;
    --accent-2: #f0353b;
    --font-color: #26211e;
    --title-font: "Akzidenz-Grotesk Black", "Akzidenz Grotesk Black", "Arial Black", sans-serif;
    --body-font: "Akzidenz-Grotesk Light", "Akzidenz Grotesk Light", "Akzidenz-Grotesk", "Helvetica Neue", Arial, sans-serif;
    --title-size: clamp(42px, 5vw, 120px);
    --body-size: clamp(16px, 1.9vw, 45px);
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--primary); color:var(--font-color); font-family:var(--body-font); font-weight:300; }}
  #app {{ display:grid; grid-template-columns: minmax(0, 1fr) minmax(460px, 34vw); height:100vh; }}
  #graph {{ width:100%; height:100%; background:linear-gradient(135deg, rgba(24,0,173,.10), transparent 30%), var(--primary); }}
  aside {{ border-left:3px solid var(--font-color); background:var(--primary); padding:28px; overflow:auto; }}
  h1 {{ margin:0 0 14px; color:var(--font-color); font-family:var(--title-font); font-size:var(--title-size); line-height:.84; letter-spacing:-.075em; text-transform:uppercase; }}
  h2 {{ margin:28px 0 10px; color:var(--accent-1); font-family:var(--title-font); font-size:14px; line-height:1; text-transform:uppercase; letter-spacing:.16em; }}
  form {{ display:flex; gap:10px; margin:20px 0 6px; }}
  input {{ flex:1; border:2px solid var(--font-color); border-radius:0; padding:12px 13px; background:var(--primary); color:var(--font-color); font-family:var(--body-font); font-size:16px; font-weight:300; }}
  button {{ border:2px solid var(--accent-1); border-radius:0; padding:12px 14px; background:var(--accent-1); color:var(--primary); font-family:var(--title-font); font-size:13px; text-transform:uppercase; letter-spacing:.05em; }}
  .controls label {{ display:block; margin:10px 0; font-size:15px; }}
  .legend {{ display:grid; grid-template-columns: 18px 1fr; gap:8px 10px; align-items:center; font-size:15px; }}
  .dot {{ width:14px; height:14px; border-radius:50%; }}
  .line-swatch {{ width:18px; height:0; border-top:3px solid var(--font-color); }}
  pre {{ white-space:pre-wrap; background:transparent; border:2px solid var(--font-color); border-radius:0; padding:14px; color:var(--font-color); font:12px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .muted {{ color:rgba(38,33,30,.72); font-size:15px; line-height:1.35; }}
  .pill {{ display:inline-block; margin:3px 4px 3px 0; padding:3px 8px; border:1px solid var(--accent-1); border-radius:999px; color:var(--accent-1); font-size:12px; }}
  .node text {{ fill:var(--font-color); paint-order:stroke; stroke:var(--primary); stroke-width:5px; stroke-linejoin:round; font-family:var(--body-font); font-size:12px; font-weight:300; pointer-events:none; }}
  .link {{ stroke:var(--accent-1); stroke-opacity:.56; }}
  .link.direct {{ stroke:var(--accent-1); stroke-opacity:.86; }}
  .link.entity {{ stroke:var(--accent-2); stroke-opacity:.78; }}
  .link.vector {{ stroke:var(--accent-1); stroke-opacity:.56; }}
  .link-label {{ fill:var(--font-color); font-size:10px; pointer-events:none; opacity:.82; paint-order:stroke; stroke:var(--primary); stroke-width:3px; }}
</style>
</head>
<body>
<div id=\"app\">
  <svg id=\"graph\"></svg>
  <aside>
    <h1>Retrieval analysis dashboard</h1>
    <div class=\"muted\">Final selected results + wider ranked candidates outside token budget.</div>
    <form id=\"queryForm\">
      <input id=\"queryInput\" name=\"query\" value=\"{escaped_query}\" placeholder=\"Enter retrieval query…\" />
      <button type=\"submit\">Graph query</button>
    </form>
    <div id=\"status\" class=\"muted\"></div>
    <h2>Controls</h2>
    <div class=\"controls\">
      <label><input id="hideOutside" type="checkbox"> hide candidates outside final result</label>
      <label><input id="showLabels" type="checkbox" checked> show labels</label>
      <label><input id="showEdgeLabels" type="checkbox"> show edge labels</label>
    </div>
    <h2>Legend</h2><div class=\"legend\" id=\"legend\"></div>
    <h2>Selected node</h2><div id=\"details\" class=\"muted\">Click a bubble.</div>
    <h2>Stats</h2><pre>{escaped_stats}</pre>
  </aside>
</div>
<script>
let graph = {data};
function nodeColor(d) {{ return d.group === 'query' || d.final_selected || d.candidate_order || d.order ? '#1800ad' : '#f0353b'; }}
const svg = d3.select('#graph');
const statusEl = document.getElementById('status');
function visibleData() {{
  const hideOutside = document.getElementById('hideOutside').checked;
  const nodes = graph.nodes.filter(n => !(hideOutside && !n.final_selected && n.group !== 'query'));
  const ids = new Set(nodes.map(n => n.id));
  const links = graph.links.filter(l => ids.has(l.source.id || l.source) && ids.has(l.target.id || l.target));
  return {{nodes: nodes.map(n => ({{...n}})), links: links.map(l => ({{...l}}))}};
}}
function radius(d) {{ return d.group === 'query' ? 19 : d.final_selected ? 12 : 7; }}
function render() {{
  const width = svg.node().clientWidth, height = svg.node().clientHeight;
  svg.selectAll('*').remove();
  const g = svg.append('g');
  svg.call(d3.zoom().scaleExtent([0.15, 4]).on('zoom', e => g.attr('transform', e.transform)));
  const data = visibleData();
  const sim = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(d => d.rel === 'direct_context_for' ? 72 : 145).strength(d => d.rel === 'direct_context_for' ? .7 : .18))
    .force('charge', d3.forceManyBody().strength(d => d.final_selected ? -440 : -180))
    .force('center', d3.forceCenter(width/2, height/2))
    .force('collision', d3.forceCollide().radius(d => radius(d)+10));
  const link = g.append('g').selectAll('line').data(data.links).join('line').attr('class', d => 'link ' + (d.rel === 'direct_context_for' ? 'direct' : d.rel === 'entity_link' ? 'entity' : d.rel === 'vector_candidate' ? 'vector' : '')).attr('stroke-width', d => d.rel === 'direct_context_for' ? 3 : d.rel === 'entity_link' ? 2 : Math.sqrt(d.weight || 1));
  const edgeLabels = g.append('g').selectAll('text').data(data.links).join('text').attr('class','link-label').text(d => d.relationship_type || d.rel.replace('_candidate','')).style('display', document.getElementById('showEdgeLabels').checked ? null : 'none');
  const node = g.append('g').selectAll('g').data(data.nodes).join('g').attr('class','node').call(drag(sim)).on('click', showDetails);
  node.append('circle').attr('r', radius).attr('fill', nodeColor).attr('opacity', d => d.final_selected || d.group === 'query' ? 1 : .42).attr('stroke', d => d.stage.includes('one_hop') || d.stage.includes('direct') ? '#1800ad' : d.final_selected ? '#26211e' : '#26211e').attr('stroke-width', d => d.stage.includes('one_hop') || d.stage.includes('direct') ? 2.6 : d.final_selected ? 1.8 : 1);
  node.append('text').attr('x', d => radius(d)+4).attr('y', 4).text(d => `${{d.order ? d.order + '. ' : d.candidate_order ? '#' + d.candidate_order + ' ' : ''}}${{d.label || d.id}}`).style('display', document.getElementById('showLabels').checked ? null : 'none').attr('opacity', d => d.final_selected || d.group === 'query' ? 1 : .55);
  sim.on('tick', () => {{ link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y); node.attr('transform', d => `translate(${{d.x}},${{d.y}})`); edgeLabels.attr('x', d => (d.source.x + d.target.x)/2).attr('y', d => (d.source.y + d.target.y)/2); }});
}}
function drag(sim) {{ return d3.drag().on('start', e => {{ if(!e.active) sim.alphaTarget(.3).restart(); e.subject.fx=e.subject.x; e.subject.fy=e.subject.y; }}).on('drag', e => {{ e.subject.fx=e.x; e.subject.fy=e.y; }}).on('end', e => {{ if(!e.active) sim.alphaTarget(0); e.subject.fx=null; e.subject.fy=null; }}); }}
function showDetails(_event, d) {{ document.getElementById('details').innerHTML = `<div><b>${{escapeHtml(d.label || d.id)}}</b></div><div class=\"muted\">${{escapeHtml(d.source_ref || d.id)}}</div><div>${{['stage:'+d.stage, 'type:'+d.type, d.final_selected ? 'FINAL' : 'outside final', d.candidate_order ? 'candidate #'+d.candidate_order : ''].filter(Boolean).map(x=>`<span class=\"pill\">${{escapeHtml(x)}}</span>`).join('')}}</div><div>${{(d.retrievers||[]).map(x=>`<span class=\"pill\">${{escapeHtml(x)}}</span>`).join('')}}</div><div>${{(d.rerank_reasons||[]).map(x=>`<span class=\"pill\">${{escapeHtml(x)}}</span>`).join('')}}</div><pre>${{escapeHtml(d.snippet || d.title || '')}}</pre>`; }}
function escapeHtml(s) {{ return String(s ?? '').replace(/[&<>\"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c])); }}
async function graphQuery(query) {{
  statusEl.textContent = 'Building graph…';
  const response = await fetch('/api/retrieval-graph?query=' + encodeURIComponent(query));
  const payload = await response.json();
  if (!response.ok || payload.status !== 'ok') {{
    statusEl.textContent = payload.error || 'Graph build failed';
    return;
  }}
  graph = payload.graph;
  document.querySelector('aside pre').textContent = JSON.stringify(graph.stats, null, 2);
  statusEl.textContent = 'Graph built: ' + (payload.report?.url || query);
  render();
}}
document.getElementById('queryForm').addEventListener('submit', event => {{
  event.preventDefault();
  const query = document.getElementById('queryInput').value.trim();
  if (query) graphQuery(query);
}});
function initLegend() {{
  const legend = document.getElementById('legend');
  [
    ['dot', 'Ranked retrieval node', '#1800ad'],
    ['dot', 'Outside-rank context node', '#f0353b'],
    ['line', 'Keyword / semantic search edge', '#1800ad'],
    ['line', 'Entity-link edge', '#f0353b'],
  ].forEach(([shape, label, color]) => legend.insertAdjacentHTML('beforeend', `<span class=\"${{shape === 'line' ? 'line-swatch' : 'dot'}}\" style=\"${{shape === 'line' ? 'border-color' : 'background'}}:${{color}}\"></span><span>${{label}}</span>`));
}}
['hideOutside','showLabels','showEdgeLabels'].forEach(id => document.getElementById(id).addEventListener('change', render));
window.addEventListener('resize', render); initLegend(); render();
</script>
</body>
</html>
"""
