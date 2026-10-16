from ingest_helpers import CC, CDC

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.application.answer import render_context, unsupported_mentions
from legal_radar.application.assunto import AssuntoResolver
from legal_radar.domain.model import Context, Dispositivo

CLT = "urn:lex:br:federal:decreto.lei:1943-05-01;5452"
RETRIEVED = [f"{CC}#art50", f"{CC}#art50_par1", f"{CDC}#art28"]


def test_a_mention_of_a_retrieved_dispositivo_is_supported():
    answer = "Nos termos do art. 50, § 1º, do Código Civil e do art. 28 do CDC."

    assert unsupported_mentions(answer, RETRIEVED) == []


def test_a_mention_of_an_article_the_sources_never_gave_is_flagged():
    answer = "Aplica-se o art. 855-A da CLT e os artigos 133 a 134 do CPC, além do art. 50 do CC."

    assert unsupported_mentions(answer, RETRIEVED) == [
        f"{CLT}#art855A",
        "urn:lex:br:federal:lei:2015-03-16;13105#art133",
        "urn:lex:br:federal:lei:2015-03-16;13105#art134",
    ]


def test_a_mention_naming_no_lei_is_never_flagged():
    assert unsupported_mentions("O art. 7º e o § 3º também valem.", RETRIEVED) == []


def test_the_context_shown_to_the_model_drops_amendment_marks():
    d = Dispositivo(
        f"{CC}#art50_par5",
        CC,
        "art50_par5",
        "Não constitui desvio de finalidade a mera expansão. (Incluído pela Lei nº 13.874/2019)",
    )

    shown = render_context(Context([d], [], {}))

    assert shown == f"[{CC}#art50_par5] Não constitui desvio de finalidade a mera expansão."


def test_a_query_with_no_letter_resolves_to_nothing_without_embedding_it():
    provider = FakeProvider()

    assert AssuntoResolver(provider).resolve("??") is None
    assert provider.calls == []
