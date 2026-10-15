import pytest
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.domain import (
    Confidence,
    Dispositivo,
    GraphBatch,
    Jurisprudencia,
    Lei,
    Origin,
    Relation,
    RelationType,
)

A = "urn:lex:br:federal:lei:2000-01-01;1"
B = "urn:lex:br:federal:lei:2001-01-01;2"
OUTSIDE = "urn:lex:br:federal:lei:2002-01-02;3"


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


def rel(type_, source, target, evidence="e", unresolved=None, confidence=Confidence.HIGH):
    return Relation(type_, source, target, confidence, Origin.RULE, evidence, unresolved)


def batch(*relations):
    ds = [
        Dispositivo(f"{A}#art1", A, "art1", "x"),
        Dispositivo(f"{A}#art2", A, "art2", "y", revoked=True, revocations=("(Revogado)",)),
    ]
    return GraphBatch(Lei(A, "A"), ds, [], [], list(relations))


def rows(driver, query):
    return [r.data() for r in driver.execute_query(query)[0]]


def test_relations_are_written_with_provenance_and_idempotently(driver):
    relations = [
        rel(RelationType.REFERENCES, f"{A}#art1", f"{A}#art2", "art. 2"),
        rel(RelationType.REVOKES, B, f"{A}#art2", "(Revogado pela Lei 2)"),
    ]
    store = Neo4jGraphStore(driver)
    store.write(batch(*relations))
    store.write(batch(*relations))

    assert rows(driver, "MATCH ()-[r:REFERENCES]->() RETURN r.confidence AS c, r.origin AS o") == [
        {"c": "HIGH", "o": "rule"}
    ]
    assert rows(
        driver, "MATCH (l:Lei {stub: true})-[:REVOKES]->(d) RETURN l.id AS l, d.id AS d"
    ) == [{"l": B, "d": f"{A}#art2"}]
    assert rows(driver, "MATCH (d:Dispositivo {revoked: true}) RETURN d.id AS id") == [
        {"id": f"{A}#art2"}
    ]


def test_reference_to_a_lei_the_graph_lacks_points_at_a_stub_lei(driver):
    store = Neo4jGraphStore(driver)
    store.write(
        batch(
            rel(RelationType.REFERENCES, f"{A}#art1", f"{OUTSIDE}#art9", confidence=Confidence.LOW)
        )
    )

    assert rows(
        driver,
        "MATCH (:Dispositivo)-[r:REFERENCES]->(l:Lei {stub: true}) "
        "RETURN l.id AS l, r.locator AS p",
    ) == [{"l": OUTSIDE, "p": "art9"}]


def test_ingesting_a_stub_lei_clears_the_stub_flag(driver):
    store = Neo4jGraphStore(driver)
    store.write(batch(rel(RelationType.REVOKES, B, f"{A}#art2")))
    store.write(GraphBatch(Lei(B, "B"), [], [], []))

    assert rows(
        driver, "MATCH (l:Lei {id: $id}) RETURN l.stub AS s, l.title AS t".replace("$id", f"'{B}'")
    ) == [{"s": None, "t": "B"}]


def test_unresolved_citations_are_kept_as_attributes(driver):
    store = Neo4jGraphStore(driver)
    unresolved = [
        rel(
            RelationType.REFERENCES,
            f"{A}#art1",
            None,
            unresolved="lei:9/2000 art3",
            confidence=Confidence.LOW,
        ),
        rel(
            RelationType.REVOKES,
            None,
            f"{A}#art2",
            unresolved="lei:8/2000",
            confidence=Confidence.LOW,
        ),
    ]
    store.write(batch(*unresolved))
    store.write(batch(*unresolved))

    assert rows(
        driver,
        "MATCH (d:Dispositivo) RETURN d.id AS id, d.unresolved_references AS r, "
        "d.unresolved_revokers AS v ORDER BY id",
    ) == [
        {"id": f"{A}#art1", "r": ["lei:9/2000 art3"], "v": None},
        {"id": f"{A}#art2", "r": None, "v": ["lei:8/2000"]},
    ]


def llm(type_, source, target, evidence="e"):
    return Relation(type_, source, target, Confidence.MEDIUM, Origin.LLM, evidence)


def test_replacing_llm_relations_swaps_them_and_keeps_rule_edges(driver):
    store = Neo4jGraphStore(driver)
    rule = rel(RelationType.REFERENCES, f"{A}#art1", f"{A}#art2", "art. 2")
    store.write(batch(rule))
    store.replace_llm_relations(
        f"{A}#art1",
        [
            llm(RelationType.DEFINES, f"{A}#art1", "abuso"),
            llm(RelationType.REFERENCES, f"{A}#art1", f"{OUTSIDE}#art9"),
        ],
    )
    store.replace_llm_relations(f"{A}#art1", [llm(RelationType.OBLIGES, f"{A}#art1", "socio")])

    assert rows(
        driver,
        "MATCH (:Dispositivo {id: $id})-[r]->(t) RETURN type(r) AS t, r.origin AS o, "
        "coalesce(t.id, '') AS target ORDER BY t".replace("$id", f"'{A}#art1'"),
    ) == [
        {"t": "OBLIGES", "o": "llm", "target": "socio"},
        {"t": "REFERENCES", "o": "rule", "target": f"{A}#art2"},
    ]


def test_a_decision_gets_llm_concept_edges_that_a_rerun_replaces(driver):
    store = Neo4jGraphStore(driver)
    decision = Jurisprudencia("STJ:1", "STJ", "REsp 1", "ementa", "decisão", "tese")
    store.write_jurisprudencia([decision])
    store.replace_llm_relations("STJ:1", [llm(RelationType.APPLIES_TO, "STJ:1", "abuso")])
    store.replace_llm_relations("STJ:1", [llm(RelationType.DEFINES, "STJ:1", "socio")])

    assert rows(
        driver,
        "MATCH (:Jurisprudencia {id: 'STJ:1'})-[r]->(t:Conceito) "
        "RETURN type(r) AS t, r.origin AS o, r.confidence AS c, t.id AS target",
    ) == [{"t": "DEFINES", "o": "llm", "c": "MEDIUM", "target": "socio"}]


def test_a_decision_gets_rule_references_to_dispositivos_stubs_and_unresolved_citations(driver):
    store = Neo4jGraphStore(driver)
    decision = Jurisprudencia("STJ:1", "STJ", "REsp 1", "ementa", "decisão", "tese")
    store.write(batch())
    store.write_jurisprudencia(
        [decision],
        [
            rel(RelationType.REFERENCES, "STJ:1", f"{A}#art1", "art. 1"),
            rel(RelationType.REFERENCES, "STJ:1", f"{OUTSIDE}#art9", confidence=Confidence.LOW),
            Relation(
                RelationType.REFERENCES,
                "STJ:1",
                None,
                Confidence.LOW,
                Origin.RULE,
                "art. 5",
                "art5",
            ),
        ],
    )
    store.write_jurisprudencia([decision], [rel(RelationType.REFERENCES, "STJ:1", f"{A}#art1")])

    assert rows(
        driver,
        "MATCH (:Jurisprudencia {id: 'STJ:1'})-[r:REFERENCES]->(t) "
        "RETURN labels(t)[0] AS l, t.id AS target ORDER BY target",
    ) == [{"l": "Dispositivo", "target": f"{A}#art1"}, {"l": "Lei", "target": OUTSIDE}]
    assert rows(
        driver,
        "MATCH (j:Jurisprudencia {id: 'STJ:1'}) RETURN j.unresolved_references AS u",
    ) == [{"u": ["art5"]}]
