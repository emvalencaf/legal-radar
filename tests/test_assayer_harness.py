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
