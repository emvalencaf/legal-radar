from pathlib import Path

import pytest
from neo4j import GraphDatabase
from test_pipeline import snapshot
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.domain import Jurisprudencia
from legal_radar.pipeline import run
from legal_radar.seed import export_seed, load_seed

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


def populate(driver) -> None:
    store = Neo4jGraphStore(driver)
    run(FIXTURE.read_text(encoding="utf-8"), FakeProvider(), store)
    store.write_jurisprudencia(
        [Jurisprudencia("STJ:1", "STJ", "REsp 1 / SP", "ementa ç", "acórdão", None)]
    )


def test_export_is_deterministic_text(driver):
    populate(driver)

    first = export_seed(driver)
    driver.execute_query("MATCH (n) DETACH DELETE n")
    populate(driver)

    assert export_seed(driver) == first
    assert first.endswith("\n")
    assert "ç" in first


def test_loading_the_seed_into_an_empty_graph_reproduces_it(driver):
    populate(driver)
    expected = snapshot(driver)
    seed = export_seed(driver)
    driver.execute_query("MATCH (n) DETACH DELETE n")

    load_seed(driver, seed)

    assert snapshot(driver) == expected
    assert export_seed(driver) == seed


def test_loading_the_seed_twice_changes_nothing(driver):
    populate(driver)
    seed = export_seed(driver)
    driver.execute_query("MATCH (n) DETACH DELETE n")

    load_seed(driver, seed)
    once = snapshot(driver)
    load_seed(driver, seed)

    assert snapshot(driver) == once
    assert export_seed(driver) == seed


def test_load_creates_uniqueness_constraints(driver):
    load_seed(driver, "")

    rows, _, _ = driver.execute_query("SHOW CONSTRAINTS YIELD labelsOrTypes")
    assert {r["labelsOrTypes"][0] for r in rows} >= {
        "Lei",
        "Dispositivo",
        "Jurisprudencia",
        "Conceito",
    }
