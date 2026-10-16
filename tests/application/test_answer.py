import pytest
from ingest_helpers import CC, CDC
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.adapters.prompt_lock import refresh
from legal_radar.application.answer import ANSWER_SCHEMA, CitationError, ask, parse_answer
from legal_radar.application.subject import SubjectResolver
from legal_radar.domain.model import CaseLaw, GraphBatch, Hop, Provision, Statute

ART_50 = f"{CC}#art50"
ART_50_1 = f"{CC}#art50_par1"
ART_51 = f"{CC}#art51"
CDC_28 = f"{CDC}#art28"
CP = "urn:lex:br:federal:lei:1940-12-07;2848"
CP_121 = f"{CP}#art121"
CP_122 = f"{CP}#art122"
TEMA = "STJ:202001090402"
OTHER = "STF:unrelated"
EXPECTED = [ART_50, ART_50_1, CDC_28, CP_121, TEMA]


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


def d(statute: str, path: str, text: str, parent: str | None = None) -> Provision:
    return Provision(
        f"{statute}#{path}", statute, path, text, f"{statute}#{parent}" if parent else None
    )


@pytest.fixture
def graph(driver):
    """Two anchor statutes, a third statute, and decisions citing provisions.

    The anchors are CC art. 50 and CDC art. 28 (art51 is outside them). art50 PARTS art50_par1;
    art28 REFERENCES CP art121 (one hop from a reached node); CP art121 REFERENCES CP art122 (a
    second hop: out of reach); TEMA cites art50; OTHER cites nothing.
    """
    store = Neo4jGraphStore(driver)
    store.write(
        GraphBatch(
            Statute(CC, "Código Civil"),
            [
                d(CC, "art50", "Desconsideração da personalidade em caso de abuso."),
                d(CC, "art50_par1", "Desvio de finalidade.", "art50"),
                d(CC, "art51", "Outro artigo."),
            ],
            [],
            [],
        )
    )
    store.write(
        GraphBatch(
            Statute(CDC, "CDC"),
            [d(CDC, "art28", "Desconsideração no consumo.")],
            [],
            [],
        )
    )
    store.write(
        GraphBatch(
            Statute(CP, "CP"),
            [
                d(CP, "art121", "Homicídio."),
                d(CP, "art122", "Equiparação."),
            ],
            [],
            [],
        )
    )
    store.write_case_law(
        [
            CaseLaw(TEMA, "STJ", "REsp 1873811", "Ementa sobre abuso.", "Provido", "Tese"),
            CaseLaw(OTHER, "STF", "RE 1", "Outra ementa.", "Negado"),
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


def test_resolves_the_subject_and_cites_graph_nodes_with_their_paths(graph, lock):
    result = ask(QUERY, SubjectResolver(FakeProvider()).resolve, graph, FakeProvider(), lock)

    assert result.subject == "desconsideração da personalidade jurídica"
    assert result.answer
    assert [c.id for c in result.citations] == sorted(EXPECTED)
    by_id = {c.id: c for c in result.citations}
    assert by_id[ART_50].path == []
    assert by_id[ART_50_1].path == [Hop("PARTS", ART_50, ART_50_1)]
    assert by_id[CDC_28].path == []
    assert by_id[CP_121].path == [Hop("REFERENCES", CDC_28, CP_121)]
    assert by_id[TEMA].path == [Hop("REFERENCES", TEMA, ART_50)]
    assert {c.id: c.kind for c in result.citations}[TEMA] == "Jurisprudencia"
    assert (
        ART_51 not in by_id and OTHER not in by_id and CP_122 not in by_id
    )  # no 2-hop REFERENCES, no unrelated nodes


def test_a_decision_citing_a_node_reached_by_references_is_not_retrieved(graph, driver):
    driver.execute_query(
        "MATCH (j:Jurisprudencia {id: $j}), (d:Dispositivo {id: $d}) MERGE (j)-[:REFERENCES]->(d)",
        j=OTHER,
        d=CP_121,
    )

    assert OTHER not in [j.id for j in graph.traverse([ART_50, CDC_28]).case_law]


def test_every_citation_resolves_to_a_graph_node(graph, lock, driver):
    result = ask(QUERY, SubjectResolver(FakeProvider()).resolve, graph, FakeProvider(), lock)

    for citation in result.citations:
        rows, _, _ = driver.execute_query(
            f"MATCH (n:{citation.kind} {{id: $id}}) RETURN n", id=citation.id
        )
        assert len(rows) == 1


def test_traversal_returns_the_same_context_for_the_same_anchor(graph):
    statutes = [CDC_28, ART_50]

    first = graph.traverse(statutes)

    assert graph.traverse(list(reversed(statutes))) == first
    assert graph.traverse(statutes) == first


def test_traversal_reports_the_statutes_revoking_a_reached_provision(graph, driver):
    driver.execute_query(
        f"""
        MATCH (l:Lei {{id: '{CP}'}}), (d:Dispositivo {{id: '{ART_50_1}'}})
        MERGE (l)-[:REVOKES {{confidence: 'HIGH'}}]->(d)
        """
    )

    context = graph.traverse([ART_50])

    assert context.revocations == [Hop("REVOKES", CP, ART_50_1, "HIGH")]
    assert graph.traverse([CDC_28]).revocations == []


def test_the_prompt_carries_the_retrieved_sources_only(graph, lock):
    provider = FakeProvider()

    ask(QUERY, SubjectResolver(FakeProvider()).resolve, graph, provider, lock)

    (prompt,) = provider.calls
    assert prompt.startswith(f"Pergunta: {QUERY}")
    assert "Desvio de finalidade." in prompt and "Ementa sobre abuso." in prompt
    assert "Equiparação." not in prompt and "Outra ementa." not in prompt


def test_an_unresolved_query_gets_no_answer_and_no_model_call(graph, lock):
    provider = FakeProvider()

    result = ask(
        "receita de bolo de cenoura", SubjectResolver(FakeProvider()).resolve, graph, provider, lock
    )

    assert (result.subject, result.answer, result.citations) == (None, None, [])
    assert provider.calls == []


def test_a_citation_outside_the_retrieved_context_is_rejected():
    schema = {**ANSWER_SCHEMA}
    schema["properties"] = {
        **ANSWER_SCHEMA["properties"],
        "citations": {**ANSWER_SCHEMA["properties"]["citations"], "items": {"enum": ["a"]}},
    }

    assert parse_answer('{"answer": "x", "citations": ["a"]}', schema) == ("x", ["a"])
    assert parse_answer('{"answer": "x", "citations": []}', schema) == ("x", [])  # it may abstain
    for reply in ['{"answer": "x", "citations": ["b"]}', "no"]:
        with pytest.raises(CitationError):
            parse_answer(reply, schema)


def test_the_cli_loads_env_without_overriding_the_environment(tmp_path, monkeypatch):
    from legal_radar.bootstrap import load_env

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


def test_corpus_lists_every_node_with_its_parent(graph):
    provisions, case_law = graph.corpus()

    by_id = {d.id: d for d in provisions}
    assert len(provisions) == 6 and by_id[ART_51].parent_id is None
    assert by_id[ART_50_1].parent_id == ART_50 and not by_id[ART_50].revoked
    assert [j.id for j in case_law] == sorted([TEMA, OTHER])
