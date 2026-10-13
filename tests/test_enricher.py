import json

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.concepts import Concept, Vocabulary
from legal_radar.domain import Confidence, Dispositivo, Origin, Relation, RelationType
from legal_radar.enricher import ENRICHMENT_PROMPT, ENRICHMENT_TEMPLATE, enrich
from legal_radar.llm import Completion
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
LOCK = refresh({ENRICHMENT_PROMPT: "c1"}, lambda name, commit: (ENRICHMENT_TEMPLATE, None))


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

    from legal_radar.enricher import candidate_targets
    from legal_radar.planalto import decode_html, parse_planalto
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

    from legal_radar.enricher import MAX_INPUT_TOKENS
    from legal_radar.router_config import enrichment_max_input_tokens, load_config

    assert enrichment_max_input_tokens({"enrichment": {"max_input_tokens": 123}}) == 123
    assert enrichment_max_input_tokens({}) == MAX_INPUT_TOKENS
    assert enrichment_max_input_tokens(load_config("router.yaml")) == MAX_INPUT_TOKENS
    for bad in (0, -1, "8000", True):
        with pytest.raises(ValueError):
            enrichment_max_input_tokens({"enrichment": {"max_input_tokens": bad}})
