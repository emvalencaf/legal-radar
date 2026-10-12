import pytest
from ingest_helpers import CC, CDC
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.answer import ANSWER_SCHEMA, CitationError, ask, parse_answer
from legal_radar.assunto import AssuntoResolver
from legal_radar.domain import Dispositivo, GraphBatch, Hop, Jurisprudencia, Lei
from legal_radar.prompts import refresh

ART_50 = f"{CC}#art-50"
ART_50_1 = f"{CC}#art-50.par-1"
ART_51 = f"{CC}#art-51"
CDC_28 = f"{CDC}#art-28"
CP = "urn:lex:br:federal:lei:1940-12-07;2848"
CP_121 = f"{CP}#art-121"
CP_122 = f"{CP}#art-122"
TEMA = "STJ:202001090402"
OTHER = "STF:unrelated"
EXPECTED = [ART_50, ART_50_1, ART_51, CDC_28, CP_121, TEMA]


@pytest.fixture(scope="module")
def neo4j():
    with Neo4jContainer("neo4j:5-community") as container:
        yield container


@pytest.fixture
def driver(neo4j):
    driver = GraphDatabase.driver(neo4j.get_connection_url(), auth=("neo4j", neo4j.password))
    driver.execute_query("MATCH (n) DETACH DELETE n")
    yield driver
    driver.close()


@pytest.fixture
def lock():
    return refresh(
        {"cited-answer": "c1"},
        lambda n, c: ("Pergunta: {query}\n\nFontes:\n{context}", ANSWER_SCHEMA),
    )


def d(lei: str, path: str, text: str, parent: str | None = None) -> Dispositivo:
    return Dispositivo(f"{lei}#{path}", lei, path, text, f"{lei}#{parent}" if parent else None)


@pytest.fixture
def graph(driver):
    """Two anchor leis, a third lei outside the assunto, and decisions citing dispositivos.

    art-50 PARTS art-50.par-1; CDC art-28 REFERENCES CP art-121 (one hop from a reached node);
    CP art-121 REFERENCES CP art-122 (a second hop: out of reach); TEMA cites art-50; OTHER
    cites nothing.
    """
    store = Neo4jGraphStore(driver)
    store.write(
        GraphBatch(
            Lei(CC, "Código Civil"),
            [
                d(CC, "art-50", "Desconsideração da personalidade em caso de abuso."),
                d(CC, "art-50.par-1", "Desvio de finalidade.", "art-50"),
                d(CC, "art-51", "Outro artigo."),
            ],
            [],
            [],
        )
    )
    store.write(
        GraphBatch(
            Lei(CDC, "CDC"),
            [d(CDC, "art-28", "Desconsideração no consumo.")],
            [],
            [],
        )
    )
    store.write(
        GraphBatch(
            Lei(CP, "CP"),
            [
                d(CP, "art-121", "Homicídio."),
                d(CP, "art-122", "Equiparação."),
            ],
            [],
            [],
        )
    )
    store.write_jurisprudencia(
        [
            Jurisprudencia(TEMA, "STJ", "REsp 1873811", "Ementa sobre abuso.", "Provido", "Tese"),
            Jurisprudencia(OTHER, "STF", "RE 1", "Outra ementa.", "Negado"),
        ]
    )
    driver.execute_query(
        f"""
        MATCH (a:Dispositivo {{id: '{ART_50}'}}), (b:Dispositivo {{id: '{CDC_28}'}}),
              (c:Dispositivo {{id: '{CP_121}'}}), (e:Dispositivo {{id: '{CP_122}'}}),
              (t:Jurisprudencia {{id: '{TEMA}'}})
        MERGE (a)-[:REFERENCES]->(b) MERGE (b)-[:REFERENCES]->(c)
        MERGE (c)-[:REFERENCES]->(e) MERGE (t)-[:REFERENCES]->(a)
        """
    )
    return Neo4jGraphReader(driver)


QUERY = "pedido de desconsiderar a personalidade da pessoa jurídica"


def test_resolves_the_assunto_and_cites_graph_nodes_with_their_paths(graph, lock):
    result = ask(QUERY, AssuntoResolver(FakeProvider()).resolve, graph, FakeProvider(), lock)

    assert result.assunto == "desconsideração da personalidade jurídica"
    assert result.answer
    assert [c.id for c in result.citations] == sorted(EXPECTED)
    by_id = {c.id: c for c in result.citations}
    assert by_id[ART_50].path == [Hop("PARTS", CC, ART_50)]
    assert by_id[ART_50_1].path == [Hop("PARTS", CC, ART_50), Hop("PARTS", ART_50, ART_50_1)]
    assert by_id[CDC_28].path == [Hop("PARTS", CDC, CDC_28)]
    assert by_id[CP_121].path == [Hop("PARTS", CDC, CDC_28), Hop("REFERENCES", CDC_28, CP_121)]
    assert by_id[TEMA].path == [Hop("PARTS", CC, ART_50), Hop("REFERENCES", TEMA, ART_50)]
    assert {c.id: c.kind for c in result.citations}[TEMA] == "Jurisprudencia"
    assert OTHER not in by_id and CP_122 not in by_id  # no 2-hop REFERENCES, no unrelated nodes


def test_a_decision_citing_a_node_reached_by_references_is_not_retrieved(graph, driver):
    driver.execute_query(
        "MATCH (j:Jurisprudencia {id: $j}), (d:Dispositivo {id: $d}) MERGE (j)-[:REFERENCES]->(d)",
        j=OTHER,
        d=CP_121,
    )

    assert OTHER not in [j.id for j in graph.traverse([CC, CDC]).jurisprudencias]


def test_every_citation_resolves_to_a_graph_node(graph, lock, driver):
    result = ask(QUERY, AssuntoResolver(FakeProvider()).resolve, graph, FakeProvider(), lock)

    for citation in result.citations:
        rows, _, _ = driver.execute_query(
            f"MATCH (n:{citation.kind} {{id: $id}}) RETURN n", id=citation.id
        )
        assert len(rows) == 1


def test_traversal_returns_the_same_context_for_the_same_anchor(graph):
    leis = [CDC, CC]

    first = graph.traverse(leis)

    assert graph.traverse(list(reversed(leis))) == first
    assert graph.traverse(leis) == first


def test_the_prompt_carries_the_retrieved_sources_only(graph, lock):
    provider = FakeProvider()

    ask(QUERY, AssuntoResolver(FakeProvider()).resolve, graph, provider, lock)

    (prompt,) = provider.calls
    assert prompt.startswith(f"Pergunta: {QUERY}")
    assert "Desvio de finalidade." in prompt and "Ementa sobre abuso." in prompt
    assert "Equiparação." not in prompt and "Outra ementa." not in prompt


def test_an_unresolved_query_gets_no_answer_and_no_model_call(graph, lock):
    provider = FakeProvider()

    result = ask(
        "receita de bolo de cenoura", AssuntoResolver(FakeProvider()).resolve, graph, provider, lock
    )

    assert (result.assunto, result.answer, result.citations) == (None, None, [])
    assert provider.calls == []


def test_a_citation_outside_the_retrieved_context_is_rejected():
    schema = {**ANSWER_SCHEMA}
    schema["properties"] = {
        **ANSWER_SCHEMA["properties"],
        "citations": {**ANSWER_SCHEMA["properties"]["citations"], "items": {"enum": ["a"]}},
    }

    assert parse_answer('{"answer": "x", "citations": ["a"]}', schema) == ("x", ["a"])
    for reply in ['{"answer": "x", "citations": ["b"]}', '{"answer": "x", "citations": []}', "no"]:
        with pytest.raises(CitationError):
            parse_answer(reply, schema)


def test_the_cli_loads_env_without_overriding_the_environment(tmp_path, monkeypatch):
    from legal_radar.__main__ import load_env

    env = tmp_path / ".env"
    env.write_text('# c\nNEW_KEY=abc\nKEPT=from-file\nQUOTED="x y"\n', encoding="utf-8")
    monkeypatch.delenv("NEW_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.setenv("KEPT", "from-env")

    load_env(env)

    import os

    assert (os.environ["NEW_KEY"], os.environ["KEPT"], os.environ["QUOTED"]) == (
        "abc",
        "from-env",
        "x y",
    )
