import pytest

pytest.importorskip("assayer")  # the `eval` extra

from ingest_helpers import CC, CC_AGENT, FakePages, lexml_pages, read
from neo4j import GraphDatabase
from test_jurisprudencia import stf, stj
from testcontainers.neo4j import Neo4jContainer

from legal_radar import assayer_harness
from legal_radar.adapters import lexml
from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.end_to_end import run_end_to_end

ASSUNTO = "desconsideração da personalidade jurídica"


class LexmlWithoutCdc(FakePages):
    """The pinned LexML pages cover the Código Civil only; the CDC search finds nothing."""

    def get(self, url: str) -> str:
        return super().get(url) if url in self.pages else "<html></html>"


@pytest.fixture(scope="module")
def neo4j():
    with Neo4jContainer("neo4j:5-community") as container:
        yield container


def test_one_run_builds_the_graph_answers_scores_and_reports(neo4j, tmp_path, monkeypatch):
    monkeypatch.setattr(lexml.time, "sleep", lambda _: None)
    monkeypatch.setattr(assayer_harness, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    driver = GraphDatabase.driver(neo4j.get_connection_url(), auth=("neo4j", neo4j.password))
    driver.execute_query("MATCH (n) DETACH DELETE n")
    try:
        result = run_end_to_end(
            ASSUNTO,
            lexml=LexmlWithoutCdc(lexml_pages().pages),
            planalto=FakePages({CC_AGENT: read("planalto/l10406_excerpt.htm")}),
            fetchers={"STF": stf(), "STJ": stj()},
            store=Neo4jGraphStore(driver),
            provider=FakeProvider(),
            report_out=tmp_path / "report" / "index.html",
            runs_dir=tmp_path / "runs",
            seed_out=tmp_path / "seed" / "graph.jsonl",
        )
        leis = driver.execute_query("MATCH (l:Lei {id: $id}) RETURN l", id=CC)[0]
        decisions = driver.execute_query("MATCH (j:Jurisprudencia) RETURN j")[0]
    finally:
        driver.close()

    assert leis and decisions
    assert result.ingestion.ingested[CC] > 0 and result.jurisprudencia.ingested > 0
    assert result.answer.assunto == ASSUNTO and result.answer.citations
    assert [r.system for r in result.evaluations] == ["graph"]
    assert list((tmp_path / "runs").glob("graph-*.json"))
    assert result.seed_path.read_text(encoding="utf-8")
    assert "Legal Radar" in result.report_path.read_text(encoding="utf-8")
