import json
import logging

import pytest
from ingest_helpers import (
    CC,
    CC_AGENT,
    FakeLocator,
    FakePages,
    FakeTexts,
    MemoryStore,
    lexml_pages,
    read,
)

from legal_radar.adapters import lexml
from legal_radar.adapters.lexml import LexmlLocator, resolve_urn, search_urn
from legal_radar.adapters.planalto import PlanaltoTextSource
from legal_radar.application.ingest import ingest
from legal_radar.domain.anchors import AnchorLei
from legal_radar.domain.model import Dispositivo
from legal_radar.domain.urn import LexmlError


def test_search_resolves_the_urn_of_the_requested_lei():
    assert search_urn(lexml_pages(), "lei 10406 2002 código civil", "10406", 2002) == CC


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(lexml.time, "sleep", lambda _: None)


def test_search_fails_after_retrying_when_the_lei_is_not_in_the_results(caplog):
    pages = lexml_pages()

    with caplog.at_level(logging.WARNING, logger=lexml.logger.name), pytest.raises(LexmlError):
        search_urn(pages, "lei 10406 2002 código civil", "99999", 1999)

    assert len(pages.requested) == 4  # first attempt + 3 retries
    assert [r.levelname for r in caplog.records] == ["WARNING"] * 3 + ["ERROR"]


def test_search_retries_when_a_result_page_misses_the_lei(caplog):
    pages = lexml_pages()
    url = "https://www.lexml.gov.br/busca/search?keyword=lei+10406+2002+c%C3%B3digo+civil"
    good = pages.pages[url]
    replies = iter(["<html></html>", good])
    pages.get = lambda u: next(replies)

    with caplog.at_level(logging.WARNING, logger=lexml.logger.name):
        assert search_urn(pages, "lei 10406 2002 código civil", "10406", 2002) == CC

    assert [r.levelname for r in caplog.records] == ["WARNING"]


def test_urn_page_yields_the_planalto_link_and_title():
    page = resolve_urn(lexml_pages(), CC)

    assert page.planalto_url == CC_AGENT
    assert page.title == "Lei nº 10.406, de 10 de Janeiro de 2002 - Código Civil"


def test_ingest_loads_the_lei_following_the_urn_page_link():
    store = MemoryStore()
    planalto = FakePages({CC_AGENT: read("planalto/l10406_excerpt.htm")})

    report = ingest(
        [AnchorLei("lei 10406 2002 código civil", "10406", 2002)],
        LexmlLocator(lexml_pages()),
        PlanaltoTextSource(planalto),
        store,
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
        [AnchorLei("lei 10406 2002 código civil", "10406", 2002)],
        LexmlLocator(lexml),
        PlanaltoTextSource(FakePages({})),
        store,
    )

    assert store.batches == []
    assert report.skipped == {CC: ["legislacao.legis.senado.leg.br"]}
    assert "skipped" in report.render()


def test_unresolvable_lei_is_reported_as_failed():
    report = ingest(
        [AnchorLei("lei 10406 2002 código civil", "1", 1)],
        LexmlLocator(lexml_pages()),
        PlanaltoTextSource(FakePages({})),
        MemoryStore(),
    )

    assert "lei 10406 2002 código civil" in report.failed


def test_ingest_extracts_relations_and_reports_them():
    store = MemoryStore()
    planalto = FakePages({CC_AGENT: read("planalto/l10406_excerpt.htm")})

    report = ingest(
        [AnchorLei("lei 10406 2002 código civil", "10406", 2002)],
        LexmlLocator(lexml_pages()),
        PlanaltoTextSource(planalto),
        store,
    )

    (batch,) = store.batches
    assert batch.relations
    assert report.relations == {CC: len(batch.relations)}
    assert any(r.type == "REVOKES" and r.target_id == f"{CC}#art44_incVI" for r in batch.relations)
    assert "relations" in report.render()


# --- ingest --enrich (#29) ---

from dataclasses import replace  # noqa: E402

from legal_radar.adapters.fake_provider import FakeProvider  # noqa: E402
from legal_radar.adapters.prompt_lock import refresh  # noqa: E402
from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore  # noqa: E402
from legal_radar.application.concepts import Concept, Vocabulary  # noqa: E402
from legal_radar.application.enricher import ENRICHMENT_PROMPT, ENRICHMENT_TEMPLATE  # noqa: E402
from legal_radar.application.ingest import EnrichConfig  # noqa: E402
from legal_radar.domain.llm import AllProvidersFailedError, Completion  # noqa: E402
from legal_radar.domain.model import EnrichmentStatus  # noqa: E402

ANCHOR = [AnchorLei("lei 10406 2002 código civil", "10406", 2002)]
VOCAB = Vocabulary(
    "direito_civil", (Concept("abuso", "Abuso", (), "Quando há abuso.", "REQUISITO"),)
)
EMPTY = Completion('{"conceitos": [], "referencias": []}')


def lock(template=ENRICHMENT_TEMPLATE):
    return refresh({ENRICHMENT_PROMPT: "c1"}, lambda name, commit: (template, None))


class EndlessProvider(FakeProvider):
    """Answers every call with `EMPTY` unless the script says otherwise."""

    def complete(self, prompt, params=None):
        if not self.script:
            self.script.append(EMPTY)
        return super().complete(prompt, params)


def chunks(*texts):
    return [Dispositivo(f"{CC}#art{i}", CC, f"art{i}", t) for i, t in enumerate(texts, 1)]


TEXTS = [  # each one has a citation the rules cannot ground
    "Há abuso, vide art. 5º, § 1º e § 2º.",
    "Sem abuso, art. 5º, § 3º e § 4º.",
    "Ver art. 6º, § 1º e § 2º.",
]


def run_enrich(metadata, provider, vocabulary=VOCAB, prompts=None, store=None):
    store = store or MemoryStore()
    config = EnrichConfig(vocabulary, provider, metadata, prompts or lock())
    report = ingest(ANCHOR, FakeLocator(), FakeTexts(chunks(*TEXTS)), store, enrichment=config)
    return report, store


def test_ingest_without_enrich_calls_no_provider_and_writes_no_report_line():
    report = ingest(
        ANCHOR,
        LexmlLocator(lexml_pages()),
        PlanaltoTextSource(FakePages({CC_AGENT: read("planalto/l10406_excerpt.htm")})),
        MemoryStore(),
    )

    assert report.enrichment == {} and "enriched" not in report.render()


def test_enrich_sends_each_llm_bound_chunk_once_and_records_it():
    metadata, provider = SqliteMetadataStore(), EndlessProvider()

    report, store = run_enrich(metadata, provider)

    counts = report.enrichment[CC]
    assert counts.processed == len(provider.calls) > 0
    assert (counts.kept, counts.returned, counts.left_pending) == (0, 0, 0)
    records = metadata.records(CC)
    assert len(records) == counts.processed
    assert {r.status for r in records.values()} == {EnrichmentStatus.OK}
    assert len(store.replaced) == counts.processed
    assert "returned to pending" in report.render()


def test_rerun_with_nothing_changed_sends_nothing():
    metadata = SqliteMetadataStore()
    first, _ = run_enrich(metadata, EndlessProvider())
    provider = EndlessProvider()

    report, _ = run_enrich(metadata, provider)

    assert provider.calls == []
    assert report.enrichment[CC].kept == first.enrichment[CC].processed
    assert report.enrichment[CC].processed == 0


def test_changed_vocabulary_or_prompt_returns_the_chunks_to_pending():
    metadata = SqliteMetadataStore()
    first, _ = run_enrich(metadata, EndlessProvider())
    n = first.enrichment[CC].processed
    other_vocab = Vocabulary("direito_civil", (replace(VOCAB.conceitos[0], label="Outro"),))
    for vocabulary, prompts in ((other_vocab, None), (VOCAB, lock(ENRICHMENT_TEMPLATE + " "))):
        provider = EndlessProvider()

        report, _ = run_enrich(metadata, provider, vocabulary, prompts)

        assert len(provider.calls) == n
        assert report.enrichment[CC].returned == n


def test_unreadable_reply_leaves_only_that_chunk_pending_and_continues():
    metadata = SqliteMetadataStore()
    provider = EndlessProvider(script=[Completion("not json")])

    report, store = run_enrich(metadata, provider)

    counts = report.enrichment[CC]
    assert counts.left_pending == 1
    assert counts.processed == len(provider.calls) - 1 > 0
    statuses = [r.status for r in metadata.records(CC).values()]
    assert statuses.count(EnrichmentStatus.PENDING) == 1
    assert len(store.replaced) == counts.processed  # the failed chunk kept its old edges


def test_exhausted_provider_stops_the_calls_but_the_lei_is_loaded():
    metadata = SqliteMetadataStore()
    provider = EndlessProvider(script=[AllProvidersFailedError("none left")])

    report, store = run_enrich(metadata, provider)

    (batch,) = store.batches
    assert batch.relations  # rule-derived edges are in the graph
    assert len(provider.calls) == 1  # no call after the first exhausted-provider error
    counts = report.enrichment[CC]
    assert counts.left_pending > 1 and counts.processed == 0
    (called,) = metadata.records(CC).values()  # the chunk that hit the error is recorded pending
    assert called.status is EnrichmentStatus.PENDING


def test_concept_edges_of_the_reply_are_handed_to_the_store():
    class Duplicating(EndlessProvider):
        def complete(self, prompt, params=None):
            return Completion(
                '{"conceitos": [{"conceito_id": "abuso", "relacao": "DEFINES", '
                '"evidence": "abuso"}], "referencias": []}'
            )

    _, store = run_enrich(SqliteMetadataStore(), Duplicating())

    assert any(r.target_id == "abuso" for _, rels in store.replaced for r in rels)


def test_chunks_the_enricher_never_sends_are_not_counted_or_recorded():
    metadata, provider = SqliteMetadataStore(), EndlessProvider()
    revoked = replace(chunks(TEXTS[0])[0], id=f"{CC}#art9", path="art9", revoked=True)
    store = MemoryStore()
    config = EnrichConfig(VOCAB, provider, metadata, lock())

    texts = FakeTexts([*chunks(*TEXTS), revoked])
    report = ingest(ANCHOR, FakeLocator(), texts, store, enrichment=config)

    counts = report.enrichment[CC]
    assert len(provider.calls) == counts.processed == len(TEXTS)
    assert f"{CC}#art9" not in metadata.records(CC)
    assert counts.left_pending == 0


def test_grounded_citation_is_forgotten_and_stays_forgotten_on_rerun():
    citation = "lei:9999/2000 art3"
    reply = json.dumps(
        {
            "conceitos": [],
            "referencias": [
                {
                    "citacao": citation,
                    "alvo": f"{CC}#art2",
                    "evidence": "art. 3º da Lei nº 9.999, de 2000",
                }
            ],
        }
    )
    texts = FakeTexts(chunks("Ver art. 3º da Lei nº 9.999, de 2000.", "Outro dispositivo."))
    metadata = SqliteMetadataStore()
    config = EnrichConfig(VOCAB, FakeProvider(script=[Completion(reply)]), metadata, lock())

    def run(store, config):
        ingest(ANCHOR, FakeLocator(), texts, store, enrichment=config)

    first = MemoryStore()
    run(first, config)
    assert first.resolved == [(f"{CC}#art1", [citation])]
    assert [r.target_id for _, rels in first.replaced for r in rels] == [f"{CC}#art2"]

    again = MemoryStore()
    run(again, replace(config, provider=FakeProvider()))
    assert again.replaced == []  # nothing was pending
    assert again.resolved == [(f"{CC}#art1", [citation])]  # the rules wrote it again: forget it


def test_too_long_chunk_is_recorded_ok_but_counted_apart():
    metadata, provider = SqliteMetadataStore(), EndlessProvider()
    config = EnrichConfig(VOCAB, provider, metadata, lock(), max_input_tokens=1)
    texts = FakeTexts(chunks(*TEXTS))

    report = ingest(ANCHOR, FakeLocator(), texts, MemoryStore(), enrichment=config)

    counts = report.enrichment[CC]
    assert (counts.too_long, counts.processed, counts.left_pending) == (len(TEXTS), 0, 0)
    assert provider.calls == []
    assert {r.skipped for r in metadata.records(CC).values()} == {"too_long"}
    assert "too long" in report.render()
