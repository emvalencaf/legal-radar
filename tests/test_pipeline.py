from pathlib import Path

import pytest
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.pipeline import run

FIXTURE = Path(__file__).parent / "fixtures" / "mini_lei.txt"


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


def snapshot(driver):
    nodes, _, _ = driver.execute_query(
        "MATCH (n) RETURN labels(n)[0] AS label, n.id AS id ORDER BY label, id"
    )
    edges, _, _ = driver.execute_query(
        "MATCH (a)-[r]->(b) RETURN a.id AS a, type(r) AS type, b.id AS b ORDER BY a, type, b"
    )
    return (
        [(r["label"], r["id"]) for r in nodes],
        [(r["a"], r["type"], r["b"]) for r in edges],
    )


def test_pipeline_writes_graph_and_is_idempotent(driver):
    store = Neo4jGraphStore(driver)
    raw = FIXTURE.read_text(encoding="utf-8")

    run(raw, FakeProvider(), store)
    first = snapshot(driver)
    run(raw, FakeProvider(), store)

    assert snapshot(driver) == first
    nodes, edges = first
    assert nodes == [
        ("Conceito", "abuso_da_personalidade"),
        ("Conceito", "decisao_judicial"),
        ("Dispositivo", "lei:99#art1"),
        ("Dispositivo", "lei:99#art1_par1"),
        ("Dispositivo", "lei:99#art1_par2"),
        ("Dispositivo", "lei:99#art2"),
        ("Lei", "lei:99"),
    ]
    assert ("lei:99", "PARTS", "lei:99#art1") in edges
    assert ("lei:99#art1", "PARTS", "lei:99#art1_par1") in edges
    assert ("lei:99#art1_par1", "RELATES_TO", "abuso_da_personalidade") in edges
    assert ("lei:99#art2", "RELATES_TO", "decisao_judicial") in edges
