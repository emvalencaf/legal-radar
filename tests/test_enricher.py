import json

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.concepts import Concept, Vocabulary
from legal_radar.domain.llm import Completion
from legal_radar.domain.model import (
    Confidence,
    Dispositivo,
    Jurisprudencia,
    Origin,
    Relation,
    RelationType,
)
from legal_radar.enricher import (
    CONCEPT_RELATIONS,
    DECISION_TEMPLATE,
    ENRICHMENT_TEMPLATE,
    enrich,
    enrich_decision,
)
from legal_radar.enrichment import DECISION_PROMPT, ENRICHMENT_PROMPT
from legal_radar.prompts import refresh

LEI = "urn:lex:br:federal:lei:2002-01-10;10406"
VOCABULARY = Vocabulary(
    "desconsideração da personalidade jurídica",
    (
        Concept("abuso", "Abuso da personalidade", ("desvio",), "Quando há abuso.", "REQUISITO"),
        Concept("socio", "Sócio", (), "Quando trata de sócios.", "ATOR"),
    ),
)
CAPUT = Dispositivo(f"{LEI}#art50", LEI, "art50", "Em caso de abuso da personalidade jurídica,")
INCISO = Dispositivo(
    f"{LEI}#art50_incI",
    LEI,
    "art50_incI",
    "os bens do   sócio respondem, nos termos do art. 3",
    CAPUT.id,
)
CANDIDATES = [f"{LEI}#art3", f"{LEI}#art50"]
TEMPLATES = {ENRICHMENT_PROMPT: ENRICHMENT_TEMPLATE, DECISION_PROMPT: DECISION_TEMPLATE}
LOCK = refresh({name: "c1" for name in TEMPLATES}, lambda name, commit: (TEMPLATES[name], None))


def reply(conceitos=(), referencias=()):
    return Completion(json.dumps({"conceitos": list(conceitos), "referencias": list(referencias)}))


def run(d=INCISO, answer=None, provider=None, **kwargs):
    provider = provider or FakeProvider(script=[answer or reply()])
    kwargs.setdefault("ancestors", [CAPUT])
    kwargs.setdefault("candidates", CANDIDATES)
    return enrich(d, VOCABULARY, provider, LOCK, **kwargs), provider


def test_concept_edge_is_medium_llm_with_a_literal_evidence():
    item = {"conceito_id": "socio", "relacao": "APPLIES_TO", "evidence": "bens do sócio"}

    result, _ = run(answer=reply([item]))

    (edge,) = result.relations
    assert edge == Relation(
        RelationType.APPLIES_TO,
        INCISO.id,
        "socio",
        Confidence.MEDIUM,
        Origin.LLM,
        "bens do   sócio",
    )


def test_out_of_vocabulary_and_non_literal_items_are_dropped_and_counted():
    items = [
        {"conceito_id": "inventado", "relacao": "DEFINES", "evidence": "bens do sócio"},
        {"conceito_id": "socio", "relacao": "DEFINES", "evidence": "texto que não existe"},
        {"conceito_id": "socio", "relacao": "INVENTADA", "evidence": "bens do sócio"},
        {"conceito_id": "socio", "relacao": "OBLIGES", "evidence": "respondem"},
    ]

    result, _ = run(answer=reply(items))

    assert [r.type for r in result.relations] == [RelationType.OBLIGES]
    assert result.dropped == 3
    assert result.out_of_vocabulary == ["inventado"]


def test_evidence_in_an_ancestor_does_not_count():
    item = {"conceito_id": "abuso", "relacao": "DEFINES", "evidence": "abuso da personalidade"}

    result, _ = run(answer=reply([item]))

    assert result.relations == [] and result.dropped == 1


def test_an_empty_reply_is_valid():
    result, _ = run()

    assert result.relations == [] and result.dropped == 0 and result.skipped is None


def test_a_malformed_reply_yields_nothing_and_is_flagged():
    result, _ = run(answer=Completion("not json"))

    assert result.relations == [] and result.failed


def test_unresolved_citation_is_grounded_in_a_candidate():
    citation = Relation(
        RelationType.REFERENCES, INCISO.id, None, Confidence.LOW, Origin.RULE, "art. 3", "art. 3"
    )
    item = {"citacao": "art. 3", "alvo": f"{LEI}#art3", "evidence": "art. 3"}

    result, provider = run(answer=reply(referencias=[item]), unresolved=[citation])

    (edge,) = result.relations
    assert (edge.type, edge.target_id, edge.confidence, edge.origin) == (
        RelationType.REFERENCES,
        f"{LEI}#art3",
        Confidence.MEDIUM,
        Origin.LLM,
    )
    assert result.resolved == [citation]
    assert "art. 3" in provider.calls[0] and f"{LEI}#art3" in provider.calls[0]


def test_a_reference_outside_the_candidates_or_without_a_citation_stays_unresolved():
    citation = Relation(
        RelationType.REFERENCES, INCISO.id, None, Confidence.LOW, Origin.RULE, "art. 3", "art. 3"
    )
    items = [
        {"citacao": "art. 3", "alvo": f"{LEI}#art999", "evidence": "art. 3"},
        {"citacao": "art. 7", "alvo": f"{LEI}#art3", "evidence": "art. 3"},
    ]

    result, _ = run(answer=reply(referencias=items), unresolved=[citation])

    assert result.relations == [] and result.resolved == [] and result.dropped == 2


def test_without_unresolved_citations_no_reference_is_ever_created():
    item = {"citacao": "art. 3", "alvo": f"{LEI}#art3", "evidence": "art. 3"}

    result, _ = run(answer=reply(referencias=[item]))

    assert result.relations == [] and result.dropped == 1


def test_prompt_carries_vocabulary_ancestors_and_target_with_a_stable_prefix():
    _, provider = run()
    _, other_provider = run(d=CAPUT, ancestors=[])
    prompt, other_prompt = provider.calls[0], other_provider.calls[0]

    assert (
        "Abuso da personalidade" in prompt and "desvio" in prompt and "Quando há abuso." in prompt
    )
    assert CAPUT.text in prompt and INCISO.text in prompt
    shared = prompt.split("## Dispositivo")[0]
    assert other_prompt.startswith(shared)


def test_the_schema_sent_enumerates_concepts_relations_and_candidates():
    seen = []
    provider = FakeProvider(script=[reply()])
    complete = provider.complete
    provider.complete = lambda prompt, params=None: seen.append(params) or complete(prompt, params)
    citation = Relation(
        RelationType.REFERENCES, INCISO.id, None, Confidence.LOW, Origin.RULE, "art. 3", "art. 3"
    )

    run(provider=provider, unresolved=[citation])

    properties = seen[0].response_schema["properties"]
    assert properties["conceitos"]["items"]["properties"]["conceito_id"]["enum"] == [
        "abuso",
        "socio",
    ]
    assert "APPLIES_TO" in properties["conceitos"]["items"]["properties"]["relacao"]["enum"]
    assert properties["referencias"]["items"]["properties"]["alvo"]["enum"] == CANDIDATES
    assert seen[0].pipeline_step == "enrich"


def test_the_schema_never_carries_an_empty_enum_when_there_is_no_unresolved_citation():
    # Constrained decoding (LM Studio) rejects `enum: []`; no citation means no reference at all.
    seen = []
    provider = FakeProvider(script=[reply()])
    complete = provider.complete
    provider.complete = lambda prompt, params=None: seen.append(params) or complete(prompt, params)

    run(provider=provider)

    references = seen[0].response_schema["properties"]["referencias"]
    assert references["maxItems"] == 0
    assert "enum" not in references["items"]["properties"]["citacao"]


def test_triage_skips_without_calling_the_llm_and_names_the_reason():
    skipped = {
        "revoked": Dispositivo("x#art1", "x", "art1", "texto", revoked=True),
        "structural": Dispositivo("x#titI", "x", "titI", "Da pessoa", kind="titulo"),
        "empty": Dispositivo("x#art2", "x", "art2", "   "),
    }
    for reason, d in skipped.items():
        result, provider = run(d=d, ancestors=[])
        assert (result.skipped, provider.calls) == (reason, [])


def test_token_ceiling_trims_the_farthest_ancestors_first():
    far = Dispositivo(f"{LEI}#far", LEI, "far", "FAR " * 400)
    near = Dispositivo(f"{LEI}#near", LEI, "near", "NEAR")
    _, unlimited = run(ancestors=[far, near])
    full = len(unlimited.calls[0]) // 4

    _, provider = run(ancestors=[far, near], max_input_tokens=full - 100)

    assert "FAR FAR" not in provider.calls[0] and "NEAR" in provider.calls[0]


def test_a_target_over_the_ceiling_is_skipped_as_too_long():
    result, provider = run(ancestors=[], max_input_tokens=10)

    assert (result.skipped, provider.calls) == ("too_long", [])


def test_a_reference_with_non_literal_evidence_is_dropped_once():
    citation = Relation(
        RelationType.REFERENCES, INCISO.id, None, Confidence.LOW, Origin.RULE, "art. 3", "art. 3"
    )
    item = {"citacao": "art. 3", "alvo": f"{LEI}#art3", "evidence": "inexistente"}

    result, _ = run(answer=reply(referencias=[item]), unresolved=[citation])

    assert result.dropped == 1


def test_ancestors_reach_the_prompt_from_the_farthest_to_the_nearest():
    far = Dispositivo(f"{LEI}#far", LEI, "far", "TEXTO-LONGE")
    near = Dispositivo(f"{LEI}#near", LEI, "near", "TEXTO-PERTO")

    _, provider = run(ancestors=[far, near])

    assert provider.calls[0].index("TEXTO-LONGE") < provider.calls[0].index("TEXTO-PERTO")


def test_a_reply_with_the_wrong_shape_is_flagged_as_failed():
    for text in ('{"conceitos": "x", "referencias": []}', '{"conceitos": []}', "[]"):
        result, _ = run(answer=Completion(text))
        assert result.failed and result.relations == []


def test_it_enriches_a_dispositivo_parsed_from_planalto_with_its_unresolved_citations():
    from pathlib import Path

    from legal_radar.adapters.planalto import decode_html, parse_planalto
    from legal_radar.enricher import candidate_targets
    from legal_radar.relations import extract_relations

    raw = (Path(__file__).parent / "fixtures" / "planalto" / "l10406_excerpt.htm").read_bytes()
    everything = parse_planalto(decode_html(raw), LEI)
    d = next(x for x in everything if x.path == "art50")
    unresolved = [r for r in extract_relations(d).relations if r.unresolved]

    result, provider = run(
        d=d,
        ancestors=[],
        unresolved=unresolved,
        candidates=candidate_targets(everything),
        answer=reply(),
    )

    assert result.skipped is None and d.text in provider.calls[0]
    assert all(c.unresolved in provider.calls[0] for c in unresolved)


def test_the_token_ceiling_is_read_from_router_yaml_with_a_default():
    import pytest

    from legal_radar.adapters.router_config import enrichment_max_input_tokens, load_config
    from legal_radar.enricher import MAX_INPUT_TOKENS

    assert enrichment_max_input_tokens({"enrichment": {"max_input_tokens": 123}}) == 123
    assert enrichment_max_input_tokens({}) == MAX_INPUT_TOKENS
    assert enrichment_max_input_tokens(load_config("router.yaml")) == MAX_INPUT_TOKENS
    for bad in (0, -1, "8000", True):
        with pytest.raises(ValueError):
            enrichment_max_input_tokens({"enrichment": {"max_input_tokens": bad}})


DECISION = Jurisprudencia(
    "STJ:202001090402",
    "STJ",
    "REsp 1873811",
    "Há abuso da personalidade quando o   sócio desvia o patrimônio.",
    "Recurso provido; o texto da decisão menciona sócio e desvio.",
    "A desconsideração exige prova do desvio.",
)


def run_decision(answer=None, decision=DECISION, **kwargs):
    provider = FakeProvider(script=[answer or reply()])
    return enrich_decision(decision, VOCABULARY, provider, LOCK, **kwargs), provider


def test_decision_edge_is_medium_llm_with_evidence_from_the_ementa_or_the_tese():
    items = [
        {"conceito_id": "socio", "relacao": "APPLIES_TO", "evidence": "o sócio desvia"},
        {"conceito_id": "abuso", "relacao": "DEFINES", "evidence": "prova do desvio"},
    ]

    result, _ = run_decision(reply(items))

    assert result.relations == [
        Relation(
            RelationType.APPLIES_TO,
            DECISION.id,
            "socio",
            Confidence.MEDIUM,
            Origin.LLM,
            "o   sócio desvia",
        ),
        Relation(
            RelationType.DEFINES,
            DECISION.id,
            "abuso",
            Confidence.MEDIUM,
            Origin.LLM,
            "prova do desvio",
        ),
    ]


def test_a_decision_can_oblige_prohibit_and_except():
    items = [
        {"conceito_id": "socio", "relacao": kind, "evidence": "o sócio desvia"}
        for kind in ("OBLIGES", "PROHIBITS", "EXCEPTS")
    ]

    result, _ = run_decision(reply(items))

    assert [r.type for r in result.relations] == [
        RelationType.OBLIGES,
        RelationType.PROHIBITS,
        RelationType.EXCEPTS,
    ]


def test_decision_drops_unknown_relations_the_decisao_and_cross_boundary_evidence():
    items = [
        {"conceito_id": "socio", "relacao": "INVENTADA", "evidence": "o sócio desvia"},
        {"conceito_id": "socio", "relacao": "RELATES_TO", "evidence": "Recurso provido"},
        {"conceito_id": "inventado", "relacao": "RELATES_TO", "evidence": "o sócio desvia"},
        {
            "conceito_id": "socio",
            "relacao": "RELATES_TO",
            "evidence": "patrimônio. A desconsideração",
        },
    ]

    result, provider = run_decision(reply(items))

    assert result.relations == [] and result.dropped == 4
    assert result.out_of_vocabulary == ["inventado"]
    assert "Recurso provido" not in provider.calls[0]


def test_decision_evidence_that_is_a_heading_in_capitals_is_dropped():
    heading = Jurisprudencia(
        "STJ:2", "STJ", "REsp 2", "ABUSO DA PERSONALIDADE JURÍDICA. Texto.", "d"
    )
    item = {
        "conceito_id": "abuso",
        "relacao": "APPLIES_TO",
        "evidence": "ABUSO DA PERSONALIDADE JURÍDICA",
    }

    result, _ = run_decision(reply([item]), decision=heading)

    assert result.relations == [] and result.dropped == 1


def test_the_decision_prompt_guards_against_false_positives():
    _, provider = run_decision()

    prompt = provider.calls[0]
    assert "lista vazia é a resposta esperada" in prompt and "o recorrente sustenta" in prompt
    assert "APPLIES_TO: a corte aplica" in prompt and "OBLIGES: a posição da corte" in prompt


def test_decision_schema_offers_the_six_concept_relations():
    seen = []
    provider = FakeProvider(script=[reply()])
    complete = provider.complete
    provider.complete = lambda prompt, params=None: seen.append(params) or complete(prompt, params)

    enrich_decision(DECISION, VOCABULARY, provider, LOCK)

    properties = seen[0].response_schema["properties"]
    enum = properties["conceitos"]["items"]["properties"]["relacao"]["enum"]
    assert enum == [t.value for t in CONCEPT_RELATIONS]
    assert list(properties) == ["conceitos"]


def test_decision_without_ementa_is_skipped():
    empty = Jurisprudencia("STF:1", "STF", "RE 1", " ", "decisão", "uma tese")

    result, provider = run_decision(decision=empty)

    assert result.skipped == "empty" and not provider.calls


def test_decision_over_the_ceiling_is_skipped():
    result, provider = run_decision(max_input_tokens=10)

    assert result.skipped == "too_long" and not provider.calls
