from dataclasses import replace
from pathlib import Path

import pytest

from legal_radar.adapters.planalto import decode_html, parse_planalto
from legal_radar.domain.model import Confidence, Dispositivo, Jurisprudencia, Origin, RelationType
from legal_radar.enrichment import EXTRACTOR_VERSION
from legal_radar.relations import extract_decision_relations, extract_relations

CC = "urn:lex:br:federal:lei:2002-01-10;10406"
CDC = "urn:lex:br:federal:lei:1990-09-11;8078"
CPC = "urn:lex:br:federal:lei:2015-03-16;13105"
LEI = "urn:lex:br:federal:lei:2000-01-01;1"


def dispositivo(text, path="art10", lei=LEI):
    return Dispositivo(f"{lei}#{path}", lei, path, text)


def targets(text, path="art10", **kwargs):
    result = extract_relations(dispositivo(text, path), **kwargs)
    return [r.target_id for r in result.relations if r.type is RelationType.REFERENCES]


def test_explicit_reference_to_a_curated_code_is_high_and_from_a_rule():
    text = "Aplica-se o art. 50 do Código Civil ao caso."

    (r,) = extract_relations(dispositivo(text)).relations

    assert (r.type, r.source_id, r.target_id) == (
        RelationType.REFERENCES,
        f"{LEI}#art10",
        CC + "#art50",
    )
    assert (r.confidence, r.origin, r.evidence) == (
        Confidence.HIGH,
        Origin.RULE,
        "art. 50 do Código Civil",
    )


def test_evidence_is_always_a_literal_substring():
    text = (
        "Ver art. 5º-A, § 2º, inciso III, da Lei nº 8.078, de 11 de setembro de 1990, e o art. 3º."
    )

    result = extract_relations(dispositivo(text))

    assert result.relations
    assert all(r.evidence in text for r in result.relations)


def test_locators_build_the_dispositivo_path():
    assert targets("art. 50, § 2º, inciso III, do Código Civil") == [CC + "#art50_par2_incIII"]
    assert targets("o parágrafo único do art. 7º, não") == [LEI + "#art7"]
    assert targets("art. 7º, parágrafo único, do CDC") == [CDC + "#art7_parUnico"]
    assert targets("art. 5º-A desta Lei") == [LEI + "#art5A"]


def test_ranges_expand_to_one_edge_per_target():
    leading = extract_relations(dispositivo("incisos I a III do art. 5º"))
    assert [r.target_id for r in leading.relations] == [LEI + "#art5"]
    assert leading.needs_llm == ["incisos I a III do art. 5º"]  # the locator must follow the artigo
    assert targets("art. 5º, incisos II a IV, do Código Civil") == [
        CC + "#art5_incII",
        CC + "#art5_incIII",
        CC + "#art5_incIV",
    ]
    assert targets("arts. 10 a 12 do Código Civil") == [CC + f"#art{n}" for n in (10, 11, 12)]


def test_relative_references_resolve_against_the_source_artigo():
    assert targets("na forma deste artigo", "art20_par1") == [LEI + "#art20"]
    assert targets("nos termos do § 2º deste artigo", "art20_par1") == [LEI + "#art20_par2"]
    assert targets("os incisos I a II deste artigo", "art20_par1") == [
        LEI + "#art20_incI",
        LEI + "#art20_incII",
    ]
    assert targets("o disposto no artigo anterior", "art20") == [LEI + "#art19"]


def test_artigo_anterior_of_a_lettered_artigo_goes_to_the_llm():
    result = extract_relations(dispositivo("conforme o artigo anterior", "art20A"))

    assert result.relations == []
    assert result.needs_llm == ["artigo anterior"]


def test_self_reference_is_dropped():
    assert targets("exceto deste artigo", "art20") == []


def test_numbered_act_resolves_from_the_table_or_the_resolver():
    assert targets("art. 3º da Lei nº 8.078/1990") == [CDC + "#art3"]
    assert targets("art. 3º da Lei nº 9.999, de 2000") == [None]

    def resolver(kind, numero, ano):
        return f"urn:lex:br:federal:{kind}:{ano}-01-01;{numero}"

    assert targets("art. 3º da Lei nº 9.999, de 2000", resolver=resolver) == [
        "urn:lex:br:federal:lei:2000-01-01;9999#art3"
    ]


def test_unresolved_target_is_low_with_the_citation_kept():
    text = "art. 3º da Lei nº 9.999, de 2000"

    result = extract_relations(dispositivo(text))

    (r,) = result.relations
    assert (r.target_id, r.confidence, r.unresolved) == (None, Confidence.LOW, "lei:9999/2000 art3")
    assert result.needs_llm == [] and result.needs_enrichment


def test_act_mention_without_artigo_references_the_lei():
    assert targets("nos termos da Lei nº 8.078/1990.") == [CDC]


def test_stub_and_missing_dispositivo_are_low_when_the_graph_is_known():
    ingested = {CC: {CC + "#art50"}}

    def confidence(text):
        return [
            r.confidence for r in extract_relations(dispositivo(text), ingested=ingested).relations
        ]

    assert confidence("art. 50 do Código Civil") == [Confidence.HIGH]
    assert confidence("art. 51 do Código Civil") == [Confidence.LOW]
    assert confidence("art. 3º do CDC") == [Confidence.LOW]


def test_revogado_mark_produces_a_revokes_edge_from_the_revoking_lei():
    text = "(Revogado pela Lei nº 8.078, de 11 de setembro de 1990)"

    (r,) = extract_relations(dispositivo(text)).relations

    assert (r.type, r.source_id, r.target_id) == (RelationType.REVOKES, CDC, f"{LEI}#art10")
    assert (r.confidence, r.origin, r.evidence) == (Confidence.HIGH, Origin.RULE, text)


def test_revogado_by_an_unknown_act_is_low_and_unresolved():
    (r,) = extract_relations(dispositivo("(Revogado pela Lei nº 1.234, de 2010)")).relations

    assert (r.source_id, r.confidence, r.unresolved) == (None, Confidence.LOW, "lei:1234/2010")


def test_redacao_dada_por_is_not_a_citation_or_a_revocation():
    text = "O prazo é de dez dias. (Redação dada pela Lei nº 8.078, de 1990)"

    result = extract_relations(dispositivo(text))

    assert result.relations == [] and result.needs_llm == []


def test_unqualified_artigo_is_the_same_lei():
    assert targets("conforme o art. 7º") == [LEI + "#art7"]


def test_unrecognised_law_name_is_not_read_as_the_same_lei():
    result = extract_relations(dispositivo("art. 7º do Estatuto da Criança"))

    assert result.relations == []
    assert result.needs_llm == ["art. 7º do Estatuto da Criança"]


def test_partly_resolved_citations_flag_the_rest():
    result = extract_relations(dispositivo("art. 5º, § 1º e § 2º, e art. 3º do CDC"))

    assert "§ 2º, e art. 3º do CDC" in result.needs_llm[0]


def test_citation_free_text_yields_nothing():
    result = extract_relations(dispositivo("Toda pessoa é capaz de direitos e deveres."))

    assert result.relations == [] and result.needs_llm == []


def test_real_planalto_chunks():
    html = decode_html((Path(__file__).parent / "fixtures/planalto/l8078_excerpt.htm").read_bytes())
    results = [extract_relations(d) for d in parse_planalto(html, CDC)]

    assert all(
        r.evidence in d.text
        for d, res in zip(parse_planalto(html, CDC), results, strict=True)
        for r in res.relations
    )


def test_act_number_without_the_no_sign_still_resolves():
    assert targets("art. 50 da Lei 10.406/2002") == [CC + "#art50"]


def test_unresolved_citation_is_not_counted_twice():
    result = extract_relations(dispositivo("art. 3º da Lei nº 9.999, de 2000"))

    assert len(result.relations) == 1 and result.needs_llm == []
    assert result.needs_enrichment


def test_resolved_chunk_needs_no_enrichment_and_unread_text_does():
    assert not extract_relations(dispositivo("art. 50 do Código Civil")).needs_enrichment
    assert extract_relations(dispositivo("art. 5º, § 1º e § 2º")).needs_enrichment


def test_result_carries_the_extractor_version_and_dropped_count():
    result = extract_relations(dispositivo("art. 50 do CC"))

    assert (result.extractor_version, result.dropped) == (EXTRACTOR_VERSION, 0)


def test_unreadable_inciso_range_goes_to_the_llm():
    result = extract_relations(dispositivo("art. 5º, incisos IV a II, do CC"))

    assert result.relations == [] and result.needs_llm


def test_roman_numerals_round_trip_and_reject_malformed():
    from legal_radar.relations import _roman, _to_roman

    assert all(_roman(_to_roman(n)) == n for n in range(1, 400))
    assert _roman("IIII") == 0 and _roman("IC") == 0


MPV = "urn:lex:br:federal:medida.provisoria:2021-12-27;1085"
L14382 = "urn:lex:br:federal:lei:2022-06-22;14382"


def cc_art44_vi():
    html = decode_html(
        (Path(__file__).parent / "fixtures/planalto/l10406_excerpt.htm").read_bytes()
    )
    return next(d for d in parse_planalto(html, CC) if d.path == "art44_incVI")


def test_revoked_inciso_yields_one_revokes_edge_per_mark_with_literal_evidence():
    urns = {("medida.provisoria", "1085", 2021): MPV, ("lei", "14382", 2022): L14382}
    d = cc_art44_vi()

    result = extract_relations(d, resolver=lambda *key: urns[key])

    revokes = {r.source_id: r for r in result.relations if r.type is RelationType.REVOKES}
    assert set(revokes) == {MPV, L14382}
    assert all(r.target_id == d.id for r in revokes.values())
    assert all(
        r.confidence is Confidence.HIGH and r.origin is Origin.RULE for r in revokes.values()
    )
    assert revokes[MPV].evidence == "(Revogado Pela Medida Provisória nº 1.085, de 2021)"
    assert revokes[MPV].evidence in d.revocations


def test_revoking_act_that_does_not_resolve_is_low_and_kept():
    result = extract_relations(cc_art44_vi())

    assert {(r.source_id, r.confidence) for r in result.relations} == {(None, Confidence.LOW)}
    assert {r.unresolved for r in result.relations} == {
        "lei:14382/2022",
        "medida.provisoria:1085/2021",
    }


DECISION = Jurisprudencia("STJ:1", "STJ", "REsp 1", "", "", None)


def test_a_decision_cites_the_dispositivos_its_ementa_and_tese_name():
    j = replace(
        DECISION,
        ementa="Desconsideração. Art. 50 do CC e arts. 133 a 134 do Código de Processo Civil.",
        tese="Aplica-se o art. 50, § 1º, do Código Civil.",
    )

    result = extract_decision_relations(j)

    assert {(r.source_id, r.target_id) for r in result.relations} == {
        ("STJ:1", CC + "#art50"),
        ("STJ:1", CC + "#art50_par1"),
        ("STJ:1", CPC + "#art133"),
        ("STJ:1", CPC + "#art134"),
    }
    assert all(
        (r.type, r.confidence, r.origin) == (RelationType.REFERENCES, Confidence.HIGH, Origin.RULE)
        for r in result.relations
    )


def test_a_decision_citation_without_a_lei_is_an_unresolved_edge_for_the_llm():
    result = extract_decision_relations(replace(DECISION, ementa="Incide o art. 50, sem a lei."))

    (r,) = result.relations
    assert (r.source_id, r.target_id, r.confidence) == ("STJ:1", None, Confidence.LOW)
    assert r.unresolved
    assert result.needs_enrichment


def test_a_decision_citation_of_an_unknown_lei_is_left_for_the_llm():
    result = extract_decision_relations(
        replace(DECISION, ementa="Ver art. 7º do Estatuto Inexistente.")
    )

    assert result.relations == []
    assert result.needs_enrichment


def test_a_decision_with_no_citation_has_nothing_to_enrich():
    result = extract_decision_relations(replace(DECISION, ementa="Nada a citar aqui."))

    assert result.relations == []
    assert not result.needs_enrichment


def test_a_decision_never_reads_its_decisao_or_this_artigo():
    j = replace(DECISION, ementa="O deste artigo e o artigo anterior.", decisao="art. 50 do CC")

    assert extract_decision_relations(j).relations == []


def test_a_decision_citation_of_a_dispositivo_the_graph_lacks_is_low():
    j = replace(DECISION, ementa="Art. 9999 do CC.")

    (r,) = extract_decision_relations(j, ingested={CC: {CC + "#art50"}}).relations

    assert r.confidence is Confidence.LOW


def decision_targets(ementa):
    result = extract_decision_relations(replace(DECISION, ementa=ementa))
    return [r.target_id for r in result.relations]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Aplica-se o § 1º do art. 50 do Código Civil.", [CC + "#art50_par1"]),
        ("O parágrafo único do art. 50 do CC.", [CC + "#art50_parUnico"]),
        ("Os incisos I a II do art. 50 do CC.", [CC + "#art50_incI", CC + "#art50_incII"]),
        ("O § 2º, inciso I, do art. 50 do CC.", [CC + "#art50_par2_incI"]),
        ("Veja o do art. 50 do CC.", [CC + "#art50"]),  # `do` alone is no locator
        ("Art. 50, § 1º, do CC.", [CC + "#art50_par1"]),  # a trailing locator wins
    ],
)
def test_a_decision_reads_a_locator_before_the_artigo(text, expected):
    assert decision_targets(text) == expected


def test_a_dispositivo_keeps_ignoring_a_locator_before_the_artigo():
    assert targets("o § 1º do art. 7º do Código Civil") == [CC + "#art7"]


def test_a_leading_locator_is_covered_and_its_evidence_literal():
    text = "Aplica-se o § 1º do art. 50 do Código Civil."

    result = extract_decision_relations(replace(DECISION, ementa=text))

    (r,) = result.relations
    assert r.evidence == "§ 1º do art. 50 do Código Civil"
    assert result.needs_llm == []


def test_a_decision_text_broken_by_line_wraps_is_read_as_one_citation():
    ementa = "INTERPRETAÇÃO DO\nART\n.\n50\nDO CÓDIGO CIVIL.\nREQUISITOS."

    result = extract_decision_relations(replace(DECISION, ementa=ementa))

    assert [r.target_id for r in result.relations] == [CC + "#art50"]
    assert (
        result.relations[0].evidence == "art. 50 do Código Civil"
    )  # read in the case the rules expect
