import json

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.adapters.prompt_lock import refresh
from legal_radar.application.concepts import Concept, Vocabulary
from legal_radar.application.enricher import ENRICHMENT_PROMPT, ENRICHMENT_TEMPLATE
from legal_radar.application.evaluation.enrichment_gold import (
    GoldError,
    Outcome,
    Thresholds,
    append_outcome,
    check_gates,
    enrich_dispositivos,
    indirect_metrics,
    load_gold,
    load_thresholds,
    persist_run,
    read_run,
    score_edges,
    start_run,
)
from legal_radar.domain.llm import Completion
from legal_radar.domain.model import Confidence, Dispositivo, Origin, Relation, RelationType

LEI = "urn:lex:br:federal:lei:2002-01-10;10406"
VOCABULARY = Vocabulary(
    "desconsideração da personalidade jurídica",
    (Concept("abuso", "Abuso", (), "Quando há abuso.", "REQUISITO"),),
)
LOCK = refresh({ENRICHMENT_PROMPT: "c1"}, lambda name, commit: (ENRICHMENT_TEMPLATE, None))
ART50 = Dispositivo(f"{LEI}#art50", LEI, "art50", "Em caso de abuso, aplica-se o art. 3 desta Lei.")
ART3 = Dispositivo(f"{LEI}#art3", LEI, "art3", "Texto qualquer sobre abuso.")

GOLD = f"""
dispositivos:
  - id: {ART50.id}
    edges:
      - {{type: REFERENCES, target: "{LEI}#art3"}}
      - {{type: APPLIES_TO, target: abuso}}
  - id: {ART3.id}
    edges: []
"""


def edge(type_, source, target, origin, evidence="abuso", unresolved=None):
    confidence = Confidence.HIGH if origin is Origin.RULE else Confidence.MEDIUM
    return Relation(type_, source, target, confidence, origin, evidence, unresolved)


def outcome(d, *relations, dropped=0):
    return Outcome(d, list(relations), dropped)


def test_gold_defaults_the_dispositivo_end_and_keeps_confirmed_negatives():
    gold = load_gold(GOLD)

    assert gold[ART3.id] == frozenset()
    assert {(e.type, e.source_id, e.target_id) for e in gold[ART50.id]} == {
        (RelationType.REFERENCES, ART50.id, f"{LEI}#art3"),
        (RelationType.APPLIES_TO, ART50.id, "abuso"),
    }


def test_gold_revokes_defaults_the_target_to_the_dispositivo():
    gold = load_gold(
        f"dispositivos:\n  - id: {ART3.id}\n    edges:\n"
        "      - {type: REVOKES, source: 'urn:lex:br:federal:lei:2020-01-01;1'}\n"
    )

    (revokes,) = gold[ART3.id]
    assert revokes.target_id == ART3.id


@pytest.mark.parametrize(
    "text",
    [
        "dispositivos:\n  - id: x\n",  # no `edges`: unannotated is not a negative
        "dispositivos:\n  - id: x\n    edges: [{type: NOPE, target: y}]\n",
        "dispositivos:\n  - id: x\n    edges: [{type: REFERENCES}]\n",
        "dispositivos:\n  - id: x\n    edges: []\n  - id: x\n    edges: []\n",
    ],
)
def test_gold_rejects_malformed_entries(text):
    with pytest.raises(GoldError):
        load_gold(text)


def test_gold_pins_the_vocabulary_it_was_annotated_against():
    pinned = f"vocabulary_hash: {VOCABULARY.hash}\n{GOLD}"

    assert load_gold(pinned, VOCABULARY) == load_gold(GOLD)


@pytest.mark.parametrize("header", ["", "vocabulary_hash: stale\n"])
def test_gold_rejects_a_missing_or_stale_vocabulary_hash(header):
    with pytest.raises(GoldError, match="vocabulary"):
        load_gold(header + GOLD, VOCABULARY)


def test_scores_per_edge_split_by_origin_and_type():
    gold = load_gold(GOLD)
    outcomes = [
        outcome(
            ART50,
            edge(RelationType.REFERENCES, ART50.id, f"{LEI}#art3", Origin.RULE),
            edge(RelationType.APPLIES_TO, ART50.id, "abuso", Origin.LLM),
            edge(RelationType.DEFINES, ART50.id, "abuso", Origin.LLM),  # not in gold
        ),
        outcome(ART3, edge(RelationType.OBLIGES, ART3.id, "abuso", Origin.LLM)),  # negative
    ]

    scores = score_edges(outcomes, gold)

    rules = scores[("rule", "all")]
    assert (rules.tp, rules.fp, rules.fn) == (1, 0, 0)
    assert rules.precision == rules.recall == rules.f1 == 1.0
    llm = scores[("llm", "CONCEPT")]
    assert (llm.tp, llm.fp, llm.fn) == (1, 2, 0)
    assert llm.precision == pytest.approx(1 / 3)
    assert scores[("llm", RelationType.DEFINES)].fp == 1
    everything = scores[("all", "all")]
    assert (everything.tp, everything.fp, everything.fn) == (2, 2, 0)


def test_only_gold_dispositivos_are_scored_and_unresolved_edges_are_not_edges():
    gold = load_gold(GOLD)
    stranger = Dispositivo(f"{LEI}#art9", LEI, "art9", "x")
    outcomes = [
        outcome(stranger, edge(RelationType.REFERENCES, stranger.id, f"{LEI}#art1", Origin.RULE)),
        outcome(ART50, edge(RelationType.REFERENCES, ART50.id, None, Origin.RULE, unresolved="x")),
    ]

    scores = score_edges(outcomes, gold)

    assert scores[("rule", "all")].fp == 0
    assert scores[("rule", "all")].fn == 1  # the missed art3 reference


def test_a_missed_gold_edge_counts_against_recall_of_each_origin():
    gold = load_gold(GOLD)

    scores = score_edges([outcome(ART50), outcome(ART3)], gold)

    assert scores[("rule", "all")].recall == 0.0
    assert scores[("rule", "all")].precision is None  # nothing predicted


def test_indirect_metrics_need_no_gold():
    d = Dispositivo(f"{LEI}#art1", LEI, "art1", "veja o art. 3 e o artigo mencionado")
    outcomes = [
        outcome(
            d,
            edge(RelationType.REFERENCES, d.id, f"{LEI}#art3", Origin.RULE, "art. 3"),
            edge(RelationType.REFERENCES, d.id, None, Origin.RULE, "o artigo mencionado", "x"),
            edge(RelationType.DEFINES, d.id, "abuso", Origin.LLM, "texto inventado"),
            dropped=1,
        )
    ]

    m = indirect_metrics(outcomes)

    assert m.target_resolved_rate == 0.5
    assert m.valid_evidence_rate == pytest.approx(2 / 3)
    assert m.drop_rate == 0.25


def test_indirect_metrics_are_undefined_without_edges():
    m = indirect_metrics([outcome(ART3)])

    assert m.target_resolved_rate is None
    assert m.valid_evidence_rate is None
    assert m.drop_rate is None


def run_gates(thresholds=None, llm_edges=True):
    thresholds = thresholds or Thresholds()
    gold = load_gold(GOLD)
    relations = [edge(RelationType.REFERENCES, ART50.id, f"{LEI}#art3", Origin.RULE, "art. 3")]
    if llm_edges:
        relations.append(edge(RelationType.APPLIES_TO, ART50.id, "abuso", Origin.LLM, "abuso"))
    outcomes = [outcome(ART50, *relations), outcome(ART3)]
    return check_gates(score_edges(outcomes, gold), indirect_metrics(outcomes), thresholds)


def test_gates_pass_when_every_threshold_is_met():
    assert run_gates() == []


def test_the_rule_gate_and_the_llm_gate_fail_independently():
    failures = run_gates(llm_edges=False)

    assert [f.gate for f in failures] == ["llm"]
    assert "recall" in failures[0].reason


def test_a_gate_with_no_gold_to_measure_recall_fails_rather_than_passes():
    failures = check_gates(score_edges([], {}), indirect_metrics([]), Thresholds())

    assert {f.gate for f in failures} == {"rules", "llm"}


def test_indirect_thresholds_are_gated():
    failures = run_gates(Thresholds(min_valid_evidence=1.0, max_drop_rate=0.0))
    assert failures == []

    d = Dispositivo(f"{LEI}#art1", LEI, "art1", "texto")
    bad = [outcome(d, edge(RelationType.DEFINES, d.id, "abuso", Origin.LLM, "nada"), dropped=3)]
    failures = check_gates(
        {}, indirect_metrics(bad), Thresholds(min_recall_rules=0, min_recall_llm=0)
    )
    assert {f.gate for f in failures} >= {"valid_evidence", "drop_rate"}


def test_thresholds_load_from_yaml(tmp_path):
    path = tmp_path / "evaluation.yml"
    path.write_text("rules: {min_precision: 0.5}\nllm: {min_recall: 0.1}\nmax_drop_rate: 0.3\n")

    t = load_thresholds(path)

    assert (t.min_precision_rules, t.min_recall_llm, t.max_drop_rate) == (0.5, 0.1, 0.3)
    assert t.min_recall_rules == Thresholds().min_recall_rules


def concept_reply():
    item = {"conceito_id": "abuso", "relacao": "APPLIES_TO", "evidence": "abuso"}
    return Completion(
        json.dumps({"conceitos": [item], "referencias": []}), tokens_in=5, tokens_out=2
    )


def test_enrich_dispositivos_merges_rule_and_llm_edges_per_dispositivo():
    provider = FakeProvider(script=[concept_reply(), concept_reply()])

    outcomes = enrich_dispositivos([ART50, ART3], VOCABULARY, provider, LOCK)

    by_id = {o.dispositivo.id: o for o in outcomes}
    kinds = {(r.type, r.origin) for r in by_id[ART50.id].relations}
    assert (RelationType.APPLIES_TO, Origin.LLM) in kinds
    assert (RelationType.REFERENCES, Origin.RULE) in kinds
    assert by_id[ART3.id].tokens_in > 0


def test_enrich_dispositivos_only_calls_the_wanted_ones_and_reports_progress():
    provider = FakeProvider(script=[concept_reply()])
    seen = []

    outcomes = enrich_dispositivos(
        [ART50, ART3],
        VOCABULARY,
        provider,
        LOCK,
        only={ART3.id},
        on_start=lambda position, total, d: seen.append(("start", position, total, d.id)),
        on_progress=lambda done, total, outcome: seen.append((done, total, outcome.dispositivo.id)),
    )

    assert [o.dispositivo.id for o in outcomes] == [ART3.id]
    assert seen == [("start", 1, 1, ART3.id), (1, 1, ART3.id)]  # announced before it is sent


def test_a_grounded_citation_replaces_its_unresolved_rule_edge():
    d = Dispositivo(f"{LEI}#art5", LEI, "art5", "Aplica-se o art. 3º da Lei nº 9.999, de 2000.")
    grounded = {
        "citacao": "lei:9999/2000 art3",
        "alvo": f"{LEI}#art3",
        "evidence": "art. 3º da Lei",
    }
    reply = Completion(json.dumps({"conceitos": [], "referencias": [grounded]}))
    provider = FakeProvider(script=[reply, concept_reply()])

    result, _ = enrich_dispositivos([d, ART3], VOCABULARY, provider, LOCK)

    refs = [r for r in result.relations if r.type is RelationType.REFERENCES]
    assert [(r.target_id, r.origin, r.unresolved) for r in refs] == [
        (f"{LEI}#art3", Origin.LLM, None)
    ]


def test_persist_run_keeps_inputs_and_outputs_as_jsonl(tmp_path):
    outcomes = [outcome(ART50, edge(RelationType.APPLIES_TO, ART50.id, "abuso", Origin.LLM))]

    path = persist_run(tmp_path, outcomes, {"vocabulary": VOCABULARY.hash}, run_id="r1")

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["run"] == {"id": "r1", "vocabulary": VOCABULARY.hash}
    assert lines[1]["input"]["text"] == ART50.text
    assert lines[1]["output"]["relations"][0]["target_id"] == "abuso"
    assert lines[1]["output"]["relations"][0]["origin"] == "llm"


def test_a_run_is_written_as_it_goes_and_read_back_to_resume(tmp_path):
    first = outcome(ART50, edge(RelationType.APPLIES_TO, ART50.id, "abuso", Origin.LLM), dropped=1)
    second = outcome(ART3)

    path = start_run(tmp_path, {"model": "m1"}, run_id="r1")
    append_outcome(path, first)
    append_outcome(path, second)  # a crash after this loses nothing

    run, outcomes = read_run(path, {d.id: d for d in (ART50, ART3)})
    assert run == {"id": "r1", "model": "m1"}
    assert outcomes == [first, second]


def test_out_of_vocabulary_ids_and_revocations_survive_the_run_file(tmp_path):
    revoked = Dispositivo(ART3.id, LEI, "art3", "texto", revocations=("(Revogado pela Lei X)",))
    first = Outcome(revoked, [], out_of_vocabulary=["invented_concept"])
    path = start_run(tmp_path, {}, run_id="r3")
    append_outcome(path, first)

    _, outcomes = read_run(path, {revoked.id: revoked})

    assert outcomes[0].out_of_vocabulary == ["invented_concept"]
    assert json.loads(path.read_text("utf-8").splitlines()[1])["input"]["revocations"] == [
        "(Revogado pela Lei X)"
    ]


def test_persist_run_still_writes_the_whole_run_at_once(tmp_path):
    path = persist_run(tmp_path, [outcome(ART3)], {"model": "m1"}, run_id="r2")

    run, outcomes = read_run(path, {ART3.id: ART3})

    assert run["id"] == "r2" and [o.dispositivo for o in outcomes] == [ART3]
