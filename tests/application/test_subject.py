import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.application.subject import SubjectResolver
from legal_radar.domain.anchors import ANCHORS
from legal_radar.domain.llm import Embedding

DESCONSIDERACAO = "desconsideração da personalidade jurídica"


def test_paraphrase_resolves_to_anchor_subject_and_its_statutes():
    resolution = SubjectResolver(FakeProvider()).resolve(
        "pedido de desconsiderar a personalidade da pessoa jurídica"
    )

    assert resolution.subject == DESCONSIDERACAO
    assert resolution.anchors == ANCHORS[DESCONSIDERACAO]
    assert {statute.numero for statute in resolution.anchors} == {"10406", "8078"}


@pytest.mark.parametrize(
    "query",
    [
        "receita de bolo de cenoura",
        "prescrição intercorrente na execução fiscal",
        "usucapião extraordinária de imóvel urbano",
        "imunidade tributária das pessoas jurídicas de direito público",
        "regime de bens no casamento e partilha em divórcio",
    ],
)
def test_unrelated_query_does_not_resolve(query):
    assert SubjectResolver(FakeProvider()).resolve(query) is None


def test_catalog_is_embedded_once_across_queries():
    provider = FakeProvider()
    resolver = SubjectResolver(provider)

    resolver.resolve("desconsideração da personalidade")
    resolver.resolve("personalidade jurídica desconsiderada")

    assert provider.calls.count(DESCONSIDERACAO) == 1


def test_catalog_is_re_embedded_when_the_provider_falls_back_to_another_model():
    provider = FakeProvider()
    resolver = SubjectResolver(provider)
    resolver.resolve("desconsideração da personalidade")
    provider.embedding_model = "other-model"

    assert resolver.resolve("desconsideração da personalidade") is not None
    assert provider.calls.count(DESCONSIDERACAO) == 2


def test_no_match_when_the_model_changes_between_query_and_catalog():
    provider = FakeProvider(
        script=[Embedding([[1.0, 0.0]], model="a"), Embedding([[1.0, 0.0]], model="b")]
    )

    assert SubjectResolver(provider).resolve("x") is None
