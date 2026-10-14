from types import SimpleNamespace

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.answer import Citation, CitedAnswer
from legal_radar.answer_evaluation import Question, UsageMeter
from legal_radar.domain import Hop
from legal_radar.llm import Completion

pytest.importorskip("assayer")  # the `eval` extra

from legal_radar.assayer_harness import Pricing, run_evaluation

A, B = "lei#a", "lei#b"


def test_run_scores_every_question_and_totals_tokens_and_cost():
    meter = UsageMeter(FakeProvider())

    def ask(query: str) -> CitedAnswer:
        meter.complete(query)  # the fake provider reports one token out, one in per word
        if query == "right":
            return CitedAnswer(
                query,
                "x",
                "ok",
                [Citation(A, "Dispositivo", [Hop("PARTS", "lei", A)], "t")],
                [A, B],
            )
        return CitedAnswer(query, "x", "ok", [Citation(B, "Dispositivo", [], "t")], [A, B])

    questions = [
        Question("one", "right", (A,), ("lei", A)),
        Question("two", "wrong now", (A,), (A,)),
    ]
    report = run_evaluation(
        questions,
        ask,
        meter,
        lambda answer: True,
        pricing=Pricing(input=1_000_000, output=2_000_000),
        experiment="t",
    )
    assert [q["scores"]["citation_correctness"] for q in report.questions] == [1.0, 0.0]
    assert report.scores["citation_correctness"] == 0.5
    assert report.scores["contradiction_surfaced"] is None
    assert report.input_tokens >= 3 and report.output_tokens >= 2
    assert report.cost_usd == pytest.approx(3 * 1.0 + 2 * 2.0)


def test_usage_meter_is_reset_per_question():
    meter = UsageMeter(FakeProvider(script=[Completion("x", tokens_in=4, tokens_out=1)] * 2))
    report = run_evaluation(
        [Question("q1", "a", (), ()), Question("q2", "b", (), ())],
        lambda q: (meter.complete(q), CitedAnswer(q, "x", "", [], []))[1],
        meter,
        lambda answer: False,
        experiment="t",
    )
    assert [q["input_tokens"] for q in report.questions] == [4, 4]


ROWS = [
    {"user_input": "q1", "response": "a1", "retrieved_contexts": ["c1"]},
    {"user_input": "q2", "response": "a2", "retrieved_contexts": ["c2"]},
    {"user_input": "q3", "response": "a3", "retrieved_contexts": ["c3"]},
]


def test_ragas_imports_despite_the_dropped_vertexai_module():
    from legal_radar.assayer_harness import _import_ragas

    _import_ragas()
    from ragas.metrics import Faithfulness

    assert Faithfulness().name == "faithfulness"


def test_ragas_faithfulness_scores_each_row_and_drops_failed_judge_scores(monkeypatch):
    import ragas

    from legal_radar.assayer_harness import ragas_faithfulness

    seen = {}

    nan = float("nan")
    result = SimpleNamespace(
        scores=[{"faithfulness": 1.0}, {"faithfulness": nan}, {"faithfulness": 0.5}]
    )

    def fake_evaluate(dataset, metrics, llm):
        seen.update(rows=len(dataset), metrics=[m.name for m in metrics], llm=llm)
        return result

    monkeypatch.setattr(ragas, "evaluate", fake_evaluate)

    assert ragas_faithfulness(ROWS, "judge") == [1.0, 0.5]
    assert seen == {"rows": 3, "metrics": ["faithfulness"], "llm": "judge"}


def test_an_abstain_question_is_scored_on_abstention_only():
    meter = UsageMeter(FakeProvider())

    def ask(query: str) -> CitedAnswer:
        if query == "off topic":
            return CitedAnswer(query, None, None, [], [])
        return CitedAnswer(query, "x", "ok", [Citation(A, "Dispositivo", [], "t")], [A])

    questions = [
        Question("answerable", "right", (A,), (A,)),
        Question("off", "off topic", (), (), abstain=True),
        Question("made-up", "gap", (), (), abstain=True),
    ]
    report = run_evaluation(
        questions, ask, meter, lambda answer: False, lambda answer: False, experiment="abstain"
    )
    scores = [q["scores"] for q in report.questions]
    assert scores[0].keys() == {"citation_correctness", "graph_path"}
    assert scores[1] == {"abstention": 1.0}  # no answer, nothing to cite
    assert scores[2] == {"abstention": 0.0}  # answered as if the graph held it
    assert report.scores["abstention"] == 0.5
    assert report.scores["citation_correctness"] == 1.0  # the abstain questions are not in it
