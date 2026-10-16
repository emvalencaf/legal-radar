import json

import pytest

from legal_radar.application.evaluation.graph_sample import (
    GraphSampleError,
    render_graph_page,
    sample_graph,
)
from legal_radar.domain.model import Confidence, Origin, Relation, RelationType

LEI = "urn:lex:br:federal:lei:2002-01-10;10406"
ART1, PAR1, ART2, ART3, ART4 = (f"{LEI}#{p}" for p in ("art1", "art1_par1", "art2", "art3", "art4"))
CONCEITO = "abuso"
DECISION = "STJ:1"


def node(label, id_):
    return {"kind": "node", "label": label, "props": {"id": id_}}


def edge(type_, a, b):
    return {"kind": "edge", "type": type_, "from": list(a), "to": list(b)}


def seed(*extra_nodes):
    lines = [
        node("Lei", LEI),
        *(node("Dispositivo", d) for d in (ART1, PAR1, ART2, ART3, ART4)),
        node("Conceito", CONCEITO),
        node("Jurisprudencia", DECISION),
        edge("PARTS", ("Lei", LEI), ("Dispositivo", ART1)),
        edge("PARTS", ("Dispositivo", ART1), ("Dispositivo", PAR1)),
        edge("PARTS", ("Lei", LEI), ("Dispositivo", ART2)),
        edge("PARTS", ("Lei", LEI), ("Dispositivo", ART3)),
        edge("PARTS", ("Lei", LEI), ("Dispositivo", ART4)),
        edge("RELATES_TO", ("Jurisprudencia", DECISION), ("Conceito", CONCEITO)),
        *extra_nodes,
    ]
    return "\n".join(json.dumps(line) for line in lines) + "\n"


def rel(type_, source, target, confidence=Confidence.HIGH, origin=Origin.RULE, evidence="trecho"):
    return Relation(type_, source, target, confidence, origin, evidence)


RELATIONS = [
    rel(RelationType.REFERENCES, PAR1, ART2, evidence="nos termos do art. 2"),
    rel(RelationType.APPLIES_TO, PAR1, CONCEITO, Confidence.MEDIUM, Origin.LLM),
    rel(RelationType.REVOKES, ART3, PAR1),  # incoming: ART3 is a 1-hop neighbour of PAR1
    rel(RelationType.REFERENCES, ART4, ART2),  # two hops from the cited node: left out
    rel(RelationType.REFERENCES, PAR1, None),  # unresolved target: not an edge
    rel(RelationType.REFERENCES, PAR1, "CF/88"),  # target outside the seed: not an edge
]


def ids(sample, role=None):
    return {n.id for n in sample.nodes if role in (None, n.role)}


def test_it_starts_from_the_cited_nodes_adds_their_ancestors_up_to_the_lei_and_one_hop_neighbours():
    sample = sample_graph(seed(), RELATIONS, [PAR1])

    assert ids(sample, "cited") == {PAR1}
    assert ids(sample, "ancestor") == {ART1, LEI}
    assert ids(sample, "neighbour") == {ART2, CONCEITO, ART3}
    assert ART4 not in ids(sample)


def test_edges_carry_type_confidence_origin_and_evidence():
    sample = sample_graph(seed(), RELATIONS, [PAR1])
    by_key = {(e.type, e.source, e.target): e for e in sample.edges}

    references = by_key[("REFERENCES", PAR1, ART2)]
    assert (references.confidence, references.origin, references.evidence) == (
        "HIGH",
        "rule",
        "nos termos do art. 2",
    )
    assert by_key[("APPLIES_TO", PAR1, CONCEITO)].origin == "llm"
    assert ("REVOKES", ART3, PAR1) in by_key
    structural = by_key[("PARTS", ART1, PAR1)]
    assert structural.confidence is None and structural.evidence is None
    assert ("PARTS", LEI, ART2) not in by_key  # ART2 is a neighbour; its own ancestry is not added


def test_seed_relates_to_edges_between_sampled_nodes_are_kept_without_properties():
    sample = sample_graph(seed(), RELATIONS, [DECISION, PAR1])

    seeded = [e for e in sample.edges if (e.type, e.source) == ("RELATES_TO", DECISION)]
    assert [(e.target, e.confidence, e.origin) for e in seeded] == [(CONCEITO, None, None)]


def test_a_cited_id_missing_from_the_seed_is_ignored():
    assert ids(sample_graph(seed(), [], ["urn:nope", ART2])) == {ART2, LEI}


def test_over_the_cap_neighbours_go_first_and_cited_nodes_and_ancestors_stay():
    many = [node("Dispositivo", f"{LEI}#x{i}") for i in range(10)]
    extra = [rel(RelationType.REFERENCES, PAR1, f"{LEI}#x{i}") for i in range(10)]

    sample = sample_graph(seed(*many), RELATIONS + extra, [PAR1], cap=6)

    assert ids(sample, "cited") == {PAR1} and ids(sample, "ancestor") == {ART1, LEI}
    assert len(sample.nodes) == 6 and len(ids(sample, "neighbour")) == 3
    assert sample.dropped == 10 + 3 - 3
    assert all(e.source in ids(sample) and e.target in ids(sample) for e in sample.edges)


def test_the_cap_never_drops_required_nodes():
    sample = sample_graph(seed(), RELATIONS, [PAR1, ART2, ART3], cap=2)

    assert ids(sample) == {PAR1, ART1, ART2, ART3, LEI}


def test_the_kept_neighbours_are_the_best_connected_then_the_most_reliable():
    low = rel(RelationType.REFERENCES, PAR1, ART3, Confidence.LOW)
    high = rel(RelationType.REFERENCES, PAR1, ART2, Confidence.HIGH)

    sample = sample_graph(seed(), [low, high], [PAR1], cap=3 + 1)

    assert ids(sample, "neighbour") == {ART2}


def test_an_invalid_seed_fails():
    with pytest.raises(GraphSampleError):
        sample_graph("not json\n", [], [])
    with pytest.raises(GraphSampleError):
        sample_graph('{"kind": "wat"}\n', [], [])


def page():
    run = {
        "system": "graph",
        "questions": [{"id": "q1", "answer": "a", "citations": [PAR1]}],
    }
    return render_graph_page(seed(), ("20261013T032054Z", RELATIONS), [run], "/*cytoscape*/")


def test_the_page_names_the_enrichment_run_and_the_citation_context():
    html = page()

    assert "20261013T032054Z" in html and "contexto das citações" in html
    assert "/*cytoscape*/" in html and "nos termos do art. 2" in html


def test_the_page_is_self_contained_and_fits_a_phone():
    html = page()

    assert 'name="viewport"' in html
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "src=" not in html


def test_the_embedded_data_cannot_close_the_script_tag():
    run = {"system": "graph", "questions": [{"id": "q", "answer": "", "citations": [PAR1]}]}
    hostile = [rel(RelationType.REFERENCES, PAR1, ART2, evidence="</script><b>x</b>")]

    html = render_graph_page(seed(), ("r1", hostile), [run], "")

    assert "</script><b>" not in html
