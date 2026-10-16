"""The graph sample page of the report (`report/graph.html`): the part of the knowledge graph
around the example answers' citations, drawn with Cytoscape.js.

Built offline from the seed, the latest enrichment run and the evaluation runs, never from a live
store. The real retrieval hops are not persisted in `eval-*.json`, so what is highlighted is the
*citation context* (contexto das citações), derived from the citations: the cited nodes, their
`PARTS` ancestors up to the `Lei` and their 1-hop neighbours through the typed relations.
"""

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from html import escape

from legal_radar.application.evaluation.report import example_answers
from legal_radar.domain.model import Confidence, Relation

CAP = 150
CITED, ANCESTOR, NEIGHBOUR = "cited", "ancestor", "neighbour"
PARTS = "PARTS"
SEED_RELATES_TO = "RELATES_TO"
LABELS = ("Lei", "Dispositivo", "Jurisprudencia", "Conceito")
CONFIDENCE_RANK = {Confidence.HIGH.value: 0, Confidence.MEDIUM.value: 1, Confidence.LOW.value: 2}


class GraphSampleError(ValueError):
    """The seed is not a seed."""


@dataclass(frozen=True)
class SampledNode:
    id: str
    label: str  # Lei, Dispositivo, Jurisprudencia or Conceito
    role: str  # cited, ancestor or neighbour


@dataclass(frozen=True)
class SampledEdge:
    type: str
    source: str
    target: str
    confidence: str | None = None  # the seed carries no edge properties
    origin: str | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class GraphSample:
    nodes: list[SampledNode]
    edges: list[SampledEdge]
    dropped: int = 0  # neighbours left out by the cap


def _parse_seed(seed: str) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """The seed's `{id: label}` and its `(type, from_id, to_id)` edges."""
    labels: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for number, line in enumerate(seed.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if record["kind"] == "node":
                labels[record["props"]["id"]] = record["label"]
            elif record["kind"] == "edge":
                edges.append((record["type"], record["from"][1], record["to"][1]))
            else:
                raise KeyError(record["kind"])
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise GraphSampleError(f"seed line {number} is not a node or an edge") from error
    return labels, edges


def sample_graph(
    seed: str, relations: Sequence[Relation], cited: Sequence[str], cap: int = CAP
) -> GraphSample:
    """The cited nodes, their ancestors and their 1-hop neighbours, at most `cap` nodes.

    Over the cap, neighbours are dropped first (the least connected to the citations, then the
    least reliable); the cited nodes and their ancestors are never dropped, even past the cap.
    """
    labels, seed_edges = _parse_seed(seed)
    parent_of = {to: source for type_, source, to in seed_edges if type_ == PARTS}

    cited_ids = [c for c in dict.fromkeys(cited) if c in labels]
    ancestors: list[str] = []
    for id_ in cited_ids:
        parent = parent_of.get(id_)
        while parent is not None and parent not in ancestors:
            ancestors.append(parent)
            parent = parent_of.get(parent)
    required = set(cited_ids) | set(ancestors)

    typed = [r for r in relations if r.source_id in labels and r.target_id in labels]
    links: dict[str, list[Relation]] = defaultdict(list)
    for r in typed:
        if r.source_id in required and r.target_id not in required:
            links[r.target_id].append(r)
        elif r.target_id in required and r.source_id not in required:
            links[r.source_id].append(r)

    def rank(id_: str):
        best = min(CONFIDENCE_RANK[r.confidence.value] for r in links[id_])
        return (-len(links[id_]), best, id_)

    ordered = sorted(links, key=rank)
    room = max(0, cap - len(required))
    neighbours = ordered[:room]
    included = required | set(neighbours)

    edges: dict[tuple[str, str, str], SampledEdge] = {}
    for r in typed:
        if r.source_id in included and r.target_id in included:
            key = (r.type.value, r.source_id, r.target_id)
            edges[key] = SampledEdge(*key, r.confidence.value, r.origin.value, r.evidence)
    for type_, source, target in seed_edges:
        key = (type_, source, target)
        if key in edges:
            continue
        if type_ == PARTS and source in ancestors and target in required:
            edges[key] = SampledEdge(*key)
        elif type_ == SEED_RELATES_TO and source in included and target in included:
            edges[key] = SampledEdge(*key)

    roles = {**dict.fromkeys(neighbours, NEIGHBOUR), **dict.fromkeys(ancestors, ANCESTOR)}
    roles.update(dict.fromkeys(cited_ids, CITED))
    nodes = [SampledNode(id_, labels[id_], role) for id_, role in roles.items()]
    return GraphSample(
        nodes,
        sorted(edges.values(), key=lambda e: (e.type, e.source, e.target)),
        len(ordered) - len(neighbours),
    )


NODE_COLOURS = {
    "Lei": "#3b5bdb",
    "Dispositivo": "#2b8a3e",
    "Jurisprudencia": "#e67700",
    "Conceito": "#ae3ec9",
}
CONFIDENCE_COLOURS = {"HIGH": "#2b8a3e", "MEDIUM": "#e67700", "LOW": "#c92a2a", "": "#868e96"}
EDGE_STYLES = {  # type: (line style, target arrow)
    "PARTS": ("solid", "tee"),
    "REFERENCES": ("dashed", "triangle"),
    "REVOKES": ("dotted", "triangle-tee"),
    "DEFINES": ("solid", "diamond"),
    "APPLIES_TO": ("dashed", "vee"),
    "OBLIGES": ("solid", "chevron"),
    "PROHIBITS": ("dotted", "triangle-backcurve"),
    "EXCEPTS": ("dotted", "diamond"),
    "RELATES_TO": ("dashed", "triangle-cross"),
}
ORIGIN_MARKERS = {"rule": "square", "llm": "circle", "": "none"}  # at the source end

PAGE_STYLE = """
:root{--bg:#f6f7fb;--card:#fff;--text:#1c2030;--muted:#5d6580;--line:#dfe3ef;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#10131c;--card:#181c29;--text:#e8eaf3;
--muted:#9aa3bf;--line:#2b3148;--accent:#8ea2ff}}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);
color:var(--text);line-height:1.5}
main{max-width:64rem;margin:0 auto;padding:1rem 1rem 3rem}
h1{font-size:1.4rem;margin:.5rem 0}a{color:var(--accent)}.muted{color:var(--muted)}
#cy{height:70vh;min-height:20rem;background:var(--card);border:1px solid var(--line);
border-radius:.8rem}
#tip{margin:.6rem 0;padding:.6rem .9rem;background:var(--card);border:1px solid var(--line);
border-radius:.6rem;min-height:3rem;overflow-wrap:anywhere}
.legend{display:flex;flex-wrap:wrap;gap:.4rem 1.2rem;font-size:.85rem;margin:.6rem 0;
padding:0;list-style:none}
.dot{display:inline-block;width:.8rem;height:.8rem;border-radius:50%;margin-right:.3rem;
vertical-align:middle}
"""

SCRIPT = """
const data = JSON.parse(document.getElementById("graph-data").textContent);
const tip = document.getElementById("tip");
const cy = cytoscape({
  container: document.getElementById("cy"),
  elements: data.elements,
  layout: {name: "cose", animate: false, nodeDimensionsIncludeLabels: true, padding: 20},
  style: [
    {selector: "node", style: {"background-color": "data(colour)", label: "data(name)",
      "font-size": 9, "text-wrap": "ellipsis", "text-max-width": 90, "text-valign": "bottom",
      "text-margin-y": 3, color: data.text, width: 18, height: 18}},
    {selector: 'node[role = "cited"]', style: {width: 30, height: 30, "border-width": 4,
      "border-color": "#f03e3e", "font-weight": "bold"}},
    {selector: 'node[role = "ancestor"]', style: {"border-width": 2, "border-color": "#f03e3e"}},
    {selector: 'node[role = "neighbour"]', style: {opacity: 0.55}},
    {selector: "edge", style: {width: 2, "curve-style": "bezier", "line-color": "data(colour)",
      "target-arrow-color": "data(colour)", "source-arrow-color": "data(colour)",
      "line-style": "data(line)", "target-arrow-shape": "data(arrow)",
      "source-arrow-shape": "data(marker)", "arrow-scale": 1.1,
      "overlay-padding": 8}},
    {selector: ".focus", style: {width: 4}},
  ],
});
function show(html) { tip.innerHTML = html; }
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function describeEdge(e) {
  const d = e.data();
  const head = "<b>" + esc(d.type) + "</b> " + esc(d.from) + " → " + esc(d.to);
  const meta = d.confidence ? " · " + esc(d.confidence) + " · " + esc(d.origin) : "";
  return head + meta + "<br>" + (d.evidence ? "“" + esc(d.evidence) + "”"
    : '<span class="muted">structural edge, no evidence</span>');
}
cy.on("mouseover tap", "edge", (ev) => {
  ev.target.addClass("focus");
  show(describeEdge(ev.target));
});
cy.on("mouseout", "edge", (ev) => ev.target.removeClass("focus"));
cy.on("mouseover tap", "node", (ev) => {
  const d = ev.target.data();
  show("<b>" + esc(d.label) + "</b> " + esc(d.id) +
    ' <span class="muted">(' + esc(d.role) + ")</span>");
});
"""


def _tail(id_: str) -> str:
    return id_.rsplit("#", 1)[-1].rsplit(":", 1)[-1] if id_ else id_


def _elements(sample: GraphSample) -> list[dict]:
    nodes = [
        {
            "data": {
                **asdict(n),
                "name": _tail(n.id),
                "colour": NODE_COLOURS.get(n.label, "#868e96"),
            }
        }
        for n in sample.nodes
    ]
    edges = []
    for i, e in enumerate(sample.edges):
        line, arrow = EDGE_STYLES.get(e.type, ("solid", "triangle"))
        edges.append(
            {
                "data": {
                    "id": f"e{i}",
                    "source": e.source,
                    "target": e.target,
                    "type": e.type,
                    "from": _tail(e.source),
                    "to": _tail(e.target),
                    "confidence": e.confidence or "",
                    "origin": e.origin or "",
                    "evidence": e.evidence or "",
                    "colour": CONFIDENCE_COLOURS[e.confidence or ""],
                    "line": line,
                    "arrow": arrow,
                    "marker": ORIGIN_MARKERS[e.origin or ""],
                }
            }
        )
    return nodes + edges


def _legend() -> str:
    nodes = "".join(
        f'<li><span class="dot" style="background:{c}"></span>{escape(k)}</li>'
        for k, c in NODE_COLOURS.items()
    )
    confidence = "".join(
        f'<li><span class="dot" style="background:{c}"></span>{k.lower()} confidence</li>'
        for k, c in CONFIDENCE_COLOURS.items()
        if k
    )
    types = "".join(
        f"<li><code>{escape(t)}</code>: {line}, {arrow} arrow</li>"
        for t, (line, arrow) in EDGE_STYLES.items()
    )
    return (
        f'<ul class="legend">{nodes}</ul><ul class="legend">{confidence}'
        "<li>grey: structural edge from the seed</li>"
        "<li>■ at the source end: rule · ● at the source end: LLM</li></ul>"
        f'<ul class="legend">{types}</ul>'
        '<ul class="legend"><li>red thick ring: cited · red thin ring: ancestor up to the lei · '
        "faded: 1-hop neighbour</li></ul>"
    )


def render_graph_page(
    seed: str,
    enrichment: tuple[str, Sequence[Relation]],
    runs: list[dict],
    cytoscape_js: str,
    cap: int = CAP,
) -> str:
    """The self-contained graph page. `enrichment` is `(run id, relations of the run)`; the cited
    nodes are those of the report's example answers."""
    run_id, relations = enrichment
    cited = [c for q in example_answers(runs) for c in q["citations"]]
    sample = sample_graph(seed, relations, cited, cap)
    payload = json.dumps({"elements": _elements(sample), "text": "#888"}, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c")  # the data can never close its <script>
    omitted = (
        f'<p class="muted">{sample.dropped} neighbouring nodes were left out to stay within '
        f"{cap} nodes.</p>"
        if sample.dropped
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Legal Radar graph sample</title><style>{PAGE_STYLE}</style></head><body><main>"
        '<a href="index.html">← back to the report</a>'
        "<h1>Knowledge graph sample · contexto das citações</h1>"
        '<p class="muted">The graph around the example answers: the nodes they cite, their '
        "ancestors up to the lei and the nodes one typed relation away. The highlight is "
        "derived from the citations (citation context), not the retrieval path actually taken. "
        f"Typed relations come from enrichment run <code>{escape(run_id)}</code>. Hover or tap an "
        f"edge to read its evidence.</p>{omitted}"
        f'<div id="cy"></div><div id="tip" aria-live="polite">Hover or tap a node or an edge.'
        f'</div>{_legend()}<script type="application/json" id="graph-data">{payload}</script>'
        f"<script>{cytoscape_js}</script><script>{SCRIPT}</script></main></body></html>"
    )
