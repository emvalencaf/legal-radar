import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.answer import ANSWER_SCHEMA
from legal_radar.domain import Dispositivo, Jurisprudencia
from legal_radar.llm import Completion, Embedding
from legal_radar.prompts import refresh
from legal_radar.rag import RagBaseline, RagError, build_chunks, build_index

LEI = "urn:lex:br:federal:lei:1940-12-07;2848"


def d(path, text, parent=None, kind="artigo", revoked=False):
    return Dispositivo(
        f"{LEI}#{path}", LEI, path, text, f"{LEI}#{parent}" if parent else None, kind, revoked
    )


CORPUS = [
    d("cap1", "Dos crimes", kind="capitulo"),
    d("art4", "São penalmente inimputáveis:", "cap1"),
    d("art4_incI", "os maiores de dezesseis e menores de dezoito anos;", "art4", "inciso"),
    d("art4_incII", "(Revogado pela Lei nº 1)", "art4", "inciso", revoked=True),
    d("art4_incIII", "(Redação dada pela Lei nº 2)", "art4", "inciso"),
    d("art5", "   ", None),
    d("art6", "Vale tudo. (Redação dada pela Lei nº 3)"),
]
DECISION = Jurisprudencia("STJ:1", "STJ", "REsp 1", "Ementa sobre abuso.", "Provido", "Tese X")


def by_id(chunks):
    return {c.id: c.text for c in chunks}


def test_naive_chunks_keep_the_raw_text_and_drop_noise():
    chunks = by_id(build_chunks(CORPUS, [DECISION], contextual=False))

    assert chunks[f"{LEI}#art4_incI"] == "os maiores de dezesseis e menores de dezoito anos;"
    assert chunks[f"{LEI}#art6"] == "Vale tudo."  # the amendment mark is not indexed
    assert set(chunks) == {f"{LEI}#{p}" for p in ("art4", "art4_incI", "art6")} | {"STJ:1"}
    assert chunks["STJ:1"] == "REsp 1. Tese: Tese X. Ementa: Ementa sobre abuso."


def test_contextual_chunk_carries_its_ancestors_but_not_structural_ones():
    chunks = by_id(build_chunks(CORPUS, [DECISION], contextual=True))

    assert chunks[f"{LEI}#art4_incI"] == (
        "São penalmente inimputáveis:\nos maiores de dezesseis e menores de dezoito anos;"
    )
    assert chunks[f"{LEI}#art4"] == "São penalmente inimputáveis:"  # no capítulo above it
    assert chunks["STJ:1"].startswith("REsp 1.")  # a decision has no ancestors


def test_chunks_are_sorted_by_id():
    ids = [c.id for c in build_chunks(CORPUS, [DECISION], contextual=False)]

    assert ids == sorted(ids)


def test_index_is_built_once_and_reused(tmp_path):
    chunks = build_chunks(CORPUS, [DECISION], contextual=False)
    path = tmp_path / "idx.sqlite"
    first = FakeProvider()

    built = build_index(chunks, first, path, batch_size=2)
    second = FakeProvider()
    reused = build_index(chunks, second, path)

    assert len(first.calls) == len(chunks) and second.calls == []
    for a, b in zip(reused.vectors, built.vectors, strict=True):
        assert a == pytest.approx(b, abs=1e-6)
    assert reused.model == built.model == "fake-embedding"


def test_index_embeds_only_what_changed(tmp_path):
    chunks = build_chunks(CORPUS, [DECISION], contextual=False)
    path = tmp_path / "idx.sqlite"
    build_index(chunks, FakeProvider(), path)
    edited = [*chunks[:-1], type(chunks[-1])(chunks[-1].id, chunks[-1].kind, "texto novo")]
    provider = FakeProvider()

    build_index(edited, provider, path)

    assert provider.calls == ["texto novo"]


def test_a_failed_batch_keeps_the_earlier_ones_so_the_build_resumes(tmp_path):
    chunks = build_chunks(CORPUS, [DECISION], contextual=False)
    path = tmp_path / "idx.sqlite"
    other = Embedding([[1.0]] * 2, model="fallback")
    flaky = FakeProvider(script=[Embedding([[0.1]] * 2, model="fake-embedding"), other])

    with pytest.raises(RagError, match="fallback"):
        build_index(chunks, flaky, path, batch_size=2)

    resumed = FakeProvider()
    build_index(chunks, resumed, path, batch_size=2)
    assert len(resumed.calls) == len(chunks) - 2


def test_an_empty_corpus_is_an_error(tmp_path):
    with pytest.raises(RagError, match="nothing to index"):
        build_index([], FakeProvider(), tmp_path / "idx.sqlite")


@pytest.fixture
def lock():
    return refresh(
        {"cited-answer": "c1"},
        lambda n, c: ("Pergunta: {query}\n\nFontes:\n{context}", ANSWER_SCHEMA),
    )


def baseline(tmp_path, lock, k, provider=None):
    chunks = build_chunks(CORPUS, [DECISION], contextual=True)
    provider = provider or FakeProvider()
    index = build_index(chunks, provider, tmp_path / "idx.sqlite")
    return RagBaseline("rag-contextual", index, provider, k, lock)


def test_retrieves_the_top_k_by_similarity(tmp_path, lock):
    rag = baseline(tmp_path, lock, k=2)

    answer = rag.ask("inimputáveis maiores de dezesseis anos")

    assert answer.retrieved == [f"{LEI}#art4_incI", f"{LEI}#art4"]


def test_answers_with_citations_that_have_no_graph_path(tmp_path, lock):
    answer = baseline(tmp_path, lock, k=3).ask("abuso na ementa")

    assert answer.answer and answer.assunto == "rag-contextual"
    assert {c.id for c in answer.citations} == set(answer.retrieved)  # the fake cites all it sees
    assert all(c.path == [] for c in answer.citations)
    assert {c.id: c.kind for c in answer.citations}["STJ:1"] == "Jurisprudencia"
    assert all(c.text for c in answer.citations)


def test_flags_an_article_the_answer_names_outside_its_sources(tmp_path, lock):
    provider = FakeProvider(script=[Embedding([[1.0] + [0.0] * 255], model="fake-embedding")])
    rag = baseline(tmp_path, lock, k=1)
    rag.provider = provider
    rag.index.vectors = [[1.0] + [0.0] * 255] * len(rag.index.chunks)

    provider.script.append(
        Completion(
            '{"answer": "Veja o art. 121 do Código Penal.", "citations": []}',
            provider="fake",
            model="m",
        )
    )
    answer = rag.ask("qualquer")

    assert answer.unsupported == ["urn:lex:br:federal:decreto.lei:1940-12-07;2848#art121"]


def test_a_query_embedded_by_another_model_is_refused(tmp_path, lock):
    rag = baseline(tmp_path, lock, k=1)
    rag.provider = FakeProvider(embedding_model="other")

    with pytest.raises(RagError, match="other"):
        rag.ask("x")
