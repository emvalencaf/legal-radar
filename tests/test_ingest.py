import pytest
from ingest_helpers import CC, CC_AGENT, FakePages, MemoryStore, lexml_pages, read

from legal_radar.anchors import AnchorLei
from legal_radar.ingest import ingest
from legal_radar.lexml import LexmlError, resolve_urn, search_urn


def test_search_resolves_the_urn_of_the_requested_lei():
    assert search_urn(lexml_pages(), "lei 10406 2002 código civil", "10406", 2002) == CC


def test_search_fails_when_the_lei_is_not_in_the_results():
    with pytest.raises(LexmlError):
        search_urn(lexml_pages(), "lei 10406 2002 código civil", "99999", 1999)


def test_urn_page_yields_the_planalto_link_and_title():
    page = resolve_urn(lexml_pages(), CC)

    assert page.planalto_url == CC_AGENT
    assert page.title == "Lei nº 10.406, de 10 de Janeiro de 2002 - Código Civil"


def test_ingest_loads_the_lei_following_the_urn_page_link():
    store = MemoryStore()
    planalto = FakePages({CC_AGENT: read("planalto/l10406_excerpt.htm")})

    report = ingest(
        [AnchorLei("lei 10406 2002 código civil", "10406", 2002)], lexml_pages(), planalto, store
    )

    assert planalto.requested == [CC_AGENT]  # the link off the URN page, never a guessed filename
    (batch,) = store.batches
    assert batch.lei.id == CC
    assert f"{CC}#art50" in {d.id for d in batch.dispositivos}
    assert report.ingested == {CC: len(batch.dispositivos)}


def test_non_planalto_destinations_are_skipped_and_reported():
    senado_only = read("lexml/urn_cc.html").replace("planalto.gov.br", "legis.senado.leg.br")
    lexml = lexml_pages()
    lexml.pages[f"https://www.lexml.gov.br/urn/{CC}"] = senado_only
    store = MemoryStore()

    report = ingest(
        [AnchorLei("lei 10406 2002 código civil", "10406", 2002)], lexml, FakePages({}), store
    )

    assert store.batches == []
    assert report.skipped == {CC: ["legislacao.legis.senado.leg.br"]}
    assert "skipped" in report.render()


def test_unresolvable_lei_is_reported_as_failed():
    report = ingest(
        [AnchorLei("lei 10406 2002 código civil", "1", 1)],
        lexml_pages(),
        FakePages({}),
        MemoryStore(),
    )

    assert "lei 10406 2002 código civil" in report.failed
