import json

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.answer import Citation, CitedAnswer
from legal_radar.answer_evaluation import (
    Question,
    UsageMeter,
    abstention,
    citation_correctness,
    contradiction_surfaced,
    graph_path,
    load_questions,
    outcome_of,
    path_nodes,
)
from legal_radar.domain.llm import Completion
from legal_radar.domain.model import Hop

A, B, C, D = "lei#a", "lei#b", "lei#c", "STJ:d"


@pytest.mark.parametrize(
    ("cited", "retrieved", "expected", "precision", "recall", "fabricated"),
    [
        ([A, B], [A, B, C], [A, B], 1.0, 1.0, []),
        ([A, C], [A, B, C], [A, B], 0.5, 0.5, []),
        ([A, "ghost"], [A, B], [A, B], 0.5, 0.5, ["ghost"]),
        ([], [A, B], [A, B], 0.0, 0.0, []),
        ([A], [A], [], 0.0, 1.0, []),  # nothing was expected: a citation cannot be right
        ([], [A], [], 1.0, 1.0, []),  # nothing expected, nothing cited
    ],
)
def test_citation_correctness(cited, retrieved, expected, precision, recall, fabricated):
    score = citation_correctness(cited, retrieved, expected)
    assert (score.precision, score.recall, score.fabricated) == (precision, recall, fabricated)


@pytest.mark.parametrize(
    ("cited", "expected", "also_ok", "precision", "recall"),
    [
        ([A, C], [A], [C], 1.0, 1.0),  # an acceptable extra is not an error
        ([A, C, D], [A], [C], 0.5, 1.0),  # another extra still is
        ([C], [A], [C], 0.0, 0.0),  # acceptable is not required: the expected one is missing
        ([A], [A], [C], 1.0, 1.0),  # and not citing it costs nothing
        ([C], [], [C], 1.0, 1.0),  # nothing but acceptable sources cited
        ([A, C], [A, C], [C], 1.0, 1.0),  # expected wins over acceptable
    ],
)
def test_acceptable_citations_do_not_count_against_precision(
    cited, expected, also_ok, precision, recall
):
    score = citation_correctness(cited, [A, C, D], expected, also_ok)

    assert (score.precision, score.recall) == (precision, recall)


def test_load_questions_reads_also_ok_and_rejects_it_on_an_abstain_question(tmp_path):
    from legal_radar.answer_evaluation import load_questions

    ok = tmp_path / "ok.yml"
    ok.write_text(
        "questions:\n  - id: q\n    query: x\n    citations: [a]\n    also_ok: [b]\n",
        encoding="utf-8",
    )
    assert load_questions(ok)[0].also_ok == ("b",)

    bad = tmp_path / "bad.yml"
    bad.write_text(
        "questions:\n  - id: q\n    query: x\n    abstain: true\n    also_ok: [b]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="also_ok"):
        load_questions(bad)


@pytest.mark.parametrize(
    ("found", "expected", "precision", "recall"),
    [
        ({A, B, C}, {A, B, C}, 1.0, 1.0),
        ({A, B, C, D}, {A, B}, 0.5, 1.0),
        ({A}, {A, B}, 1.0, 0.5),
        (set(), {A}, 0.0, 0.0),
        (set(), set(), 1.0, 1.0),
    ],
)
def test_graph_path(found, expected, precision, recall):
    score = graph_path(found, expected)
    assert (score.precision, score.recall) == (precision, recall)


def test_path_nodes_are_the_cited_nodes_and_every_node_their_hops_cross():
    citations = [
        Citation(A, "Dispositivo", [Hop("PARTS", "lei", A)]),
        Citation(D, "Jurisprudencia", [Hop("PARTS", "lei", B), Hop("REFERENCES", D, B)]),
    ]
    assert path_nodes(citations) == {"lei", A, B, D}


@pytest.mark.parametrize(
    ("pairs", "cited", "flags", "expected"),
    [
        ([], [A], True, None),  # no labeled contradiction: not applicable
        ([(A, D)], [A, D], True, 1.0),  # both sides cited and the answer flags it
        ([(A, D)], [A, D], False, 0.0),  # both sides cited, but it silently picks one
        ([(A, D)], [A], True, 0.0),  # one side never reached the answer
        ([(A, D), (B, C)], [A, D, B], True, 0.5),
    ],
)
def test_contradiction_surfaced(pairs, cited, flags, expected):
    judged = []

    def judge(answer: str) -> bool:
        judged.append(answer)
        return flags

    assert contradiction_surfaced("the answer", cited, pairs, judge) == expected
    if expected is None:
        assert judged == []  # no pair, no judge call


def test_usage_meter_sums_the_tokens_of_every_call_since_the_last_reset():
    provider = FakeProvider(
        script=[
            Completion("x", tokens_in=10, tokens_out=3),
            Completion("y", tokens_in=5, tokens_out=2),
            Completion("z", tokens_in=7, tokens_out=1),
        ]
    )
    meter = UsageMeter(provider)
    meter.complete("one")
    meter.complete("two")
    assert (meter.input_tokens, meter.output_tokens, meter.calls) == (15, 5, 2)
    meter.reset()
    meter.complete("three")
    assert (meter.input_tokens, meter.output_tokens, meter.calls) == (7, 1, 1)
    assert meter.model == provider.model


def test_outcome_carries_the_usage_metadata_assayer_reads():
    answer = CitedAnswer(
        "q", "assunto", "resposta", [Citation(A, "Dispositivo", [], text="t")], [A, B]
    )
    outcome = outcome_of(answer, usage=(12, 4))
    assert outcome.usage_metadata == {"input_tokens": 12, "output_tokens": 4}
    assert outcome["citations"] == [A]
    assert outcome["retrieved"] == [A, B]
    assert outcome["answer"] == "resposta"


def test_outcome_keeps_the_hops_that_led_to_each_citation():
    path = [Hop("PARTS", B, A), Hop("REFERENCES", A, D)]
    outcome = outcome_of(CitedAnswer("q", "a", "r", [Citation(D, "Jurisprudencia", path)]), (0, 0))
    assert outcome["citation_paths"] == {
        D: [["PARTS", B, A], ["REFERENCES", A, D]],
    }


def test_unanswered_question_has_no_citations():
    outcome = outcome_of(CitedAnswer("q", None, None, []), usage=(0, 0))
    assert outcome["citations"] == []
    assert outcome["answer"] == ""


def test_load_questions(tmp_path):
    path = tmp_path / "q.yml"
    path.write_text(
        "assunto: x\nquestions:\n"
        "  - id: q1\n    query: o que é?\n    citations: [a]\n    nodes: [a, b]\n"
        "  - id: q2\n    query: e agora?\n    citations: [a]\n    nodes: [a]\n"
        "    contradictions: [[a, b]]\n",
        encoding="utf-8",
    )
    first, second = load_questions(path)
    assert first == Question("q1", "o que é?", ("a",), ("a", "b"), ())
    assert second.contradictions == (("a", "b"),)


def test_load_questions_rejects_a_duplicate_id(tmp_path):
    path = tmp_path / "q.yml"
    path.write_text(
        "questions:\n  - {id: q, query: a, citations: [], nodes: []}\n"
        "  - {id: q, query: b, citations: [], nodes: []}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_questions(path)


def test_the_shipped_question_set_loads():
    from legal_radar.answer_evaluation import QUESTION_PATHS

    for path in QUESTION_PATHS.values():
        assert len(load_questions(path)) >= 5
        json.dumps([q.query for q in load_questions(path)])


@pytest.mark.parametrize(
    ("answer", "expected", "judge", "score"),
    [
        ("", True, False, 1.0),  # nothing resolved: no answer is the right one
        ("   ", True, False, 1.0),
        ("As fontes não tratam disso.", True, True, 1.0),
        ("O prazo é de dez anos.", True, False, 0.0),  # answered as if the sources sufficed
        ("O prazo é de dez anos.", False, False, None),  # answerable: not scored
        ("", False, True, None),
    ],
)
def test_abstention(answer, expected, judge, score):
    assert abstention(answer, expected, lambda a: judge) == score


def test_an_abstain_question_expects_no_citation_and_an_answerable_one_expects_some(tmp_path):
    path = tmp_path / "q.yml"
    path.write_text(
        "questions:\n  - {id: a, query: q, abstain: true, citations: [x], nodes: []}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="abstains"):
        load_questions(path)
    path.write_text(
        "questions:\n  - {id: a, query: q, citations: [], nodes: []}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="abstain: true"):
        load_questions(path)
