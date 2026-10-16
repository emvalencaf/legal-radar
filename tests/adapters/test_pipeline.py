from pathlib import Path

import pytest
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.fixture.pipeline import run
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.domain.model import Jurisprudencia

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mini_lei.txt"


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


def test_pipeline_writes_graph_and_is_idempotent(driver, tag_lock):
    store = Neo4jGraphStore(driver)
    raw = FIXTURE.read_text(encoding="utf-8")

    run(raw, FakeProvider(), store, tag_lock)
    first = snapshot(driver)
    run(raw, FakeProvider(), store, tag_lock)

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
    assert ("lei:99", "PARTS", "lei:99#art1_par1") not in edges
    assert ("lei:99#art1_par1", "RELATES_TO", "abuso_da_personalidade") in edges
    assert ("lei:99#art2", "RELATES_TO", "decisao_judicial") in edges


def test_ingested_lei_is_loaded_with_parts_edges_and_reload_is_idempotent(driver):
    from ingest_helpers import CC, CC_AGENT, FakePages, lexml_pages, read

    from legal_radar.application.ingest import ingest
    from legal_radar.domain.anchors import AnchorLei

    store = Neo4jGraphStore(driver)
    anchors = [AnchorLei("lei 10406 2002 código civil", "10406", 2002)]
    planalto = FakePages({CC_AGENT: read("planalto/l10406_excerpt.htm")})

    ingest(anchors, lexml_pages(), planalto, store)
    first = snapshot(driver)
    ingest(anchors, lexml_pages(), planalto, store)

    assert snapshot(driver) == first
    _, edges = first
    chapter = f"{CC}#parteGeral_livroI_tituloII_capituloI"
    assert (CC, "PARTS", f"{CC}#parteGeral") in edges
    assert (chapter, "PARTS", f"{CC}#art50") in edges
    assert (f"{CC}#art50", "PARTS", f"{CC}#art50_par2") in edges
    assert (f"{CC}#art50_par2", "PARTS", f"{CC}#art50_par2_incI") in edges
    assert (CC, "PARTS", f"{CC}#art50") not in edges


def test_jurisprudencia_is_loaded_keyed_by_court_native_id_and_reload_is_idempotent(driver):
    store = Neo4jGraphStore(driver)
    items = [
        Jurisprudencia("STJ:202001090402", "STJ", "REsp 1873811 / SP", "ementa", "acórdão", "tese")
    ]

    store.write_jurisprudencia(items)
    store.write_jurisprudencia(items)

    rows, _, _ = driver.execute_query(
        "MATCH (j:Jurisprudencia) RETURN j.id AS id, j.tese AS tese, j.decisao AS decisao"
    )
    assert [(r["id"], r["tese"], r["decisao"]) for r in rows] == [
        ("STJ:202001090402", "tese", "acórdão")
    ]
