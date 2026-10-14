import json

import pytest
from ingest_helpers import FIXTURES, MemoryStore

from legal_radar.adapters.stf import StfFetcher
from legal_radar.adapters.stj import StjFetcher
from legal_radar.domain import Jurisprudencia
from legal_radar.jurisprudencia import SEEDS, Seed, ingest_jurisprudencia

STF_SEED = "sjur550030"
STJ_SEED = "202001090402"


class FakeJsonApi:
    def __init__(self, replies: dict[str, str]):
        self.replies = replies  # query string -> raw response
        self.bodies: list[dict] = []

    def post_json(self, url: str, body: dict) -> str:
        self.bodies.append(body)
        query = body["query"]["bool"]["must"][1]["query_string"]["query"]
        return self.replies[query]


class FakeForm:
    def __init__(self, html: str):
        self.html = html
        self.submitted: list[tuple[str, dict]] = []

    def submit_form(self, url: str, form: str, fields: dict[str, str]) -> str:
        self.submitted.append((form, fields))
        return self.html


def fixture(name: str) -> str:
    return (FIXTURES / "jurisprudencia" / name).read_text(encoding="utf-8")


def stf() -> StfFetcher:
    return StfFetcher(
        FakeJsonApi(
            {'titulo:"RE 1387795"': fixture("stf_seed.json"), "assunto": fixture("stf_search.json")}
        )
    )


def stj() -> StjFetcher:
    return StjFetcher(FakeForm(fixture("stj_search.html")))


def test_stf_hits_carry_ementa_tese_and_decisao_keyed_by_the_native_id():
    hits = {j.id: j for j in stf().search('titulo:"RE 1387795"', 10)}

    tema_1232 = hits[f"STF:{STF_SEED}"]
    assert tema_1232.number == "RE 1387795"
    assert tema_1232.ementa.startswith("Recurso extraordinário com repercussão geral")
    assert "grupo econômico" in tema_1232.tese
    assert tema_1232.decisao.startswith("Após o voto do Ministro Dias Toffoli")
    assert hits["STF:repercussao-geral12823"].tese is None


def test_stf_restricts_the_search_to_acordaos_and_the_requested_size():
    api = FakeJsonApi({"assunto": fixture("stf_search.json")})

    StfFetcher(api).search("assunto", 5)

    (body,) = api.bodies
    assert body["size"] == 5
    assert body["query"]["bool"]["must"][0] == {"term": {"base": "acordaos"}}


def test_stj_documents_are_parsed_from_the_result_page_and_deduplicated():
    form = FakeForm(fixture("stj_search.html"))

    hits = StjFetcher(form).search("tema repetitivo 1210", 10)

    assert form.submitted == [
        ("frmPesquisaJurHeader", {"livre": "tema repetitivo 1210", "b": "ACOR"})
    ]
    assert [j.id for j in hits] == ["STJ:202001090402", "STJ:202001068480", "STJ:202601342504"]
    tema_1210 = hits[0]
    assert tema_1210.number == "REsp 1873811 / SP"
    assert tema_1210.tese.startswith('"Nas relações jurídicas de direito civil e empresarial')
    assert tema_1210.ementa.startswith("DIREITO CIVIL. RECURSO ESPECIAL REPETITIVO")
    assert tema_1210.decisao.startswith("Vistos e relatados")
    assert hits[2].tese is None


def test_stj_search_honours_the_limit():
    assert len(stj().search("x", 2)) == 2


def test_both_courts_look_the_same_to_the_pipeline_and_the_seeds_are_loaded_first():
    store = MemoryStore()
    fetchers = {"STF": stf(), "STJ": stj()}
    seeds = [Seed("STF", STF_SEED, 'titulo:"RE 1387795"'), Seed("STJ", STJ_SEED, "REsp 1873811")]

    report = ingest_jurisprudencia(
        fetchers, store, seeds=seeds, searches={"STF": "assunto", "STJ": "x"}
    )

    (items,) = store.jurisprudencia
    ids = [j.id for j in items]
    assert ids[:2] == [f"STF:{STF_SEED}", f"STJ:{STJ_SEED}"]
    assert len(ids) == len(set(ids)) == 2 + 5 + 2  # seeds, STF top hits, STJ hits left after dedup
    assert all(isinstance(j, Jurisprudencia) and j.ementa and j.decisao for j in items)
    assert report.failed == {}
    assert report.ingested == len(items)


def test_a_seed_missing_from_its_court_results_is_reported_and_the_rest_still_load():
    store = MemoryStore()
    seeds = [Seed("STF", "sjur0", 'titulo:"RE 1387795"'), Seed("STJ", STJ_SEED, "REsp 1873811")]

    report = ingest_jurisprudencia({"STF": stf(), "STJ": stj()}, store, seeds=seeds, searches={})

    assert list(report.failed) == ["STF:sjur0"]
    assert [j.id for j in store.jurisprudencia[0]] == [f"STJ:{STJ_SEED}"]
    assert "failed" in report.render()


def test_the_pinned_manifest_has_tema_1210_core_and_tema_1232_tangential():
    assert {(s.court, s.native_id) for s in SEEDS} == {("STJ", STJ_SEED), ("STF", STF_SEED)}


def test_stf_fixture_is_raw_json_of_the_api_envelope():
    assert json.loads(fixture("stf_seed.json"))["result"]["hits"]["hits"]


@pytest.mark.live
def test_live_sources_return_the_seed_precedents():
    from legal_radar.adapters.pages import BrowserPageSource

    browser = BrowserPageSource(channel="chrome")
    try:
        store = MemoryStore()
        report = ingest_jurisprudencia(
            {"STF": StfFetcher(browser), "STJ": StjFetcher(browser)}, store
        )
    finally:
        browser.close()
    assert report.failed == {}
    ids = {j.id for j in store.jurisprudencia[0]}
    assert {f"STF:{STF_SEED}", f"STJ:{STJ_SEED}"} <= ids


# --- ingest-jurisprudencia --enrich (#65) ---

from legal_radar.adapters.fake_provider import FakeProvider  # noqa: E402
from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore  # noqa: E402
from legal_radar.concepts import Concept, Vocabulary  # noqa: E402
from legal_radar.domain import EnrichmentStatus, RelationType  # noqa: E402
from legal_radar.enricher import DECISION_TEMPLATE  # noqa: E402
from legal_radar.enrichment import DECISION_PROMPT  # noqa: E402
from legal_radar.ingest import EnrichConfig  # noqa: E402
from legal_radar.llm import AllProvidersFailedError, Completion  # noqa: E402
from legal_radar.prompts import refresh  # noqa: E402

VOCAB = Vocabulary(
    "desconsideração", (Concept("abuso", "Abuso", (), "Quando há abuso.", "REQUISITO"),)
)
SEEDS_ONLY = [Seed("STJ", STJ_SEED, "REsp 1873811")]
NO_CONCEPTS = Completion('{"conceitos": []}')


class Scripted(FakeProvider):
    """Answers `NO_CONCEPTS` once the script runs out."""

    def complete(self, prompt, params=None):
        if not self.script:
            self.script.append(NO_CONCEPTS)
        return super().complete(prompt, params)


def enrich_run(metadata, provider, store=None):
    store = store or MemoryStore()
    lock = refresh({DECISION_PROMPT: "c1"}, lambda name, commit: (DECISION_TEMPLATE, None))
    config = EnrichConfig(VOCAB, provider, metadata, lock)
    report = ingest_jurisprudencia(
        {"STJ": stj()}, store, seeds=SEEDS_ONLY, searches={}, enrichment=config
    )
    return report, store


def test_enrich_sends_each_decision_once_and_a_rerun_keeps_it():
    metadata, provider, store = SqliteMetadataStore(), Scripted(), MemoryStore()

    report, _ = enrich_run(metadata, provider, store)
    again, _ = enrich_run(metadata, provider, store)

    assert report.enrichment["STJ"].processed == 1 and len(provider.calls) == 1
    assert again.enrichment["STJ"].kept == 1 and len(provider.calls) == 1
    assert [chunk for chunk, _ in store.replaced] == [f"STJ:{STJ_SEED}"]
    assert "enriched STJ: 1 processed" in report.render()


def test_enrich_writes_llm_concept_edges_with_the_decisions_own_evidence():
    store = MemoryStore()
    hit = next(h for h in stj().search("REsp 1873811", 10) if h.id == f"STJ:{STJ_SEED}")
    phrase = "a desconsideração da personalidade jurídica requer a efetiva comprovação"
    assert phrase in hit.tese
    reply = {"conceito_id": "abuso", "relacao": "APPLIES_TO", "evidence": phrase}
    provider = Scripted(script=[Completion(json.dumps({"conceitos": [reply]}))])

    enrich_run(SqliteMetadataStore(), provider, store)

    ((chunk, relations),) = store.replaced
    assert chunk == hit.id
    assert [(r.type, r.target_id, r.source_id) for r in relations] == [
        (RelationType.APPLIES_TO, "abuso", hit.id)
    ]


def test_an_exhausted_provider_leaves_the_decision_pending():
    metadata = SqliteMetadataStore()
    provider = Scripted(script=[AllProvidersFailedError("down")])

    report, store = enrich_run(metadata, provider)

    assert report.enrichment["STJ"].left_pending == 1 and store.replaced == []
    (record,) = metadata.records("STJ").values()
    assert record.status is EnrichmentStatus.PENDING


def test_without_enrich_no_provider_is_called_and_the_report_has_no_enrichment_line():
    report = ingest_jurisprudencia({"STJ": stj()}, MemoryStore(), seeds=SEEDS_ONLY, searches={})

    assert report.enrichment == {} and "enriched" not in report.render()
