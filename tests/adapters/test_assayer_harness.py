from types import SimpleNamespace

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.application.answer import Citation, CitedAnswer
from legal_radar.application.evaluation.answers import Question, System, UsageMeter
from legal_radar.domain.llm import Completion
from legal_radar.domain.model import Hop

pytest.importorskip("assayer")  # the `eval` extra

from legal_radar.adapters.assayer.harness import Pricing, run_evaluation

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
    from legal_radar.adapters.assayer.harness import _import_ragas

    _import_ragas()
    from ragas.metrics import Faithfulness

    assert Faithfulness().name == "faithfulness"


def test_ragas_faithfulness_scores_each_row_and_drops_failed_judge_scores(monkeypatch):
    import ragas

    from legal_radar.adapters.assayer.harness import ragas_faithfulness

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
    assert scores[0].keys() == {"citation_correctness", "graph_path", "grounded_mentions"}
    assert scores[1] == {"abstention": 1.0, "grounded_mentions": 1.0}  # nothing answered or cited
    assert scores[2] == {"abstention": 0.0, "grounded_mentions": 1.0}  # answered as if it held it
    assert report.scores["abstention"] == 0.5
    assert report.scores["citation_correctness"] == 1.0  # the abstain questions are not in it


def test_an_answer_naming_an_article_outside_its_sources_scores_zero_on_grounded_mentions():
    def ask(query: str) -> CitedAnswer:
        unsupported = ["lei#clt"] if query == "bad" else []
        return CitedAnswer(query, "x", "ok", [], [A], unsupported)

    report = run_evaluation(
        [Question("g", "good", (), (), abstain=True), Question("b", "bad", (), (), abstain=True)],
        ask,
        UsageMeter(FakeProvider()),
        lambda answer: False,
        experiment="t",
    )

    assert [q["scores"]["grounded_mentions"] for q in report.questions] == [1.0, 0.0]
    assert report.scores["grounded_mentions"] == 0.5


def test_a_baseline_without_graph_paths_reports_n_a_and_scores_per_level():
    meter = UsageMeter(FakeProvider())

    def ask(query: str) -> CitedAnswer:
        cited = [Citation(A, "Dispositivo", [], "t")] if query == "right" else []
        return CitedAnswer(query, "rag-naive", "ok", cited, [A])

    questions = [
        Question("one", "right", (A,), (A,), level="facil"),
        Question("two", "wrong", (A,), (A,), level="medio"),
        Question("three", "right", (A,), (A,)),
    ]
    report = run_evaluation(
        questions,
        ask,
        meter,
        lambda answer: False,
        experiment="t",
        system=System("rag-naive", 5),
    )

    assert report.scores["graph_path"] is None and "graph_path" not in report.questions[0]["scores"]
    assert (report.system, report.k) == ("rag-naive", 5)
    assert {n: s["citation_correctness"] for n, s in report.by_level.items()} == {
        "base": 1.0,
        "facil": 1.0,
        "medio": 0.0,
    }
    assert [q["nivel"] for q in report.questions] == ["facil", "medio", None]
    assert "rag-naive@5" in report.render()


def _resumable(tmp_path, fingerprint="f1"):
    from legal_radar.application.evaluation.answers import Checkpoint

    return Checkpoint(tmp_path / "ck.json", fingerprint)


QUESTIONS = [Question("one", "q1", (A,), (A,)), Question("two", "q2", (A,), (A,))]


def test_a_run_that_dies_resumes_without_asking_the_answered_questions_again(tmp_path):
    meter = UsageMeter(FakeProvider())
    asked = []

    def ask(query: str) -> CitedAnswer:
        asked.append(query)
        meter.complete(query)
        if query == "q2" and asked.count("q2") == 1:
            raise RuntimeError("network down")
        return CitedAnswer(
            query, "x", "ok", [Citation(A, "Dispositivo", [Hop("PARTS", "l", A)], "t")], [A]
        )

    with pytest.raises(RuntimeError, match="network down"):
        run_evaluation(QUESTIONS, ask, meter, lambda a: False, checkpoint=_resumable(tmp_path))

    report = run_evaluation(
        QUESTIONS, ask, UsageMeter(FakeProvider()), lambda a: False, checkpoint=_resumable(tmp_path)
    )

    assert asked == ["q1", "q2", "q2"]  # q1 was not asked on the second run
    assert report.scores["citation_correctness"] == 1.0
    assert report.scores["graph_path"] is not None  # the cached answer kept its path
    assert report.input_tokens > 0  # the answered question's tokens still count


def test_a_checkpoint_of_other_questions_or_prompts_is_discarded(tmp_path):
    first = _resumable(tmp_path)
    first.save("one", CitedAnswer("q1", "x", "stale", [], []), (1, 1))

    assert _resumable(tmp_path).done.keys() == {"one"}
    assert _resumable(tmp_path, "f2").done == {}  # another fingerprint starts over
    assert _resumable(tmp_path, "f2").path.read_text().count("\n") == 1  # only the header is left


def test_a_checkpoint_line_cut_short_by_a_crash_is_ignored(tmp_path):
    first = _resumable(tmp_path)
    first.save("one", CitedAnswer("q1", "x", "ok", [], []), (1, 1))
    with first.path.open("a") as file:
        file.write('{"id": "two", "ans')

    assert _resumable(tmp_path).done.keys() == {"one"}


def test_checkpoint_for_resumes_the_same_run_and_drops_it_when_questions_or_prompts_change(
    tmp_path, monkeypatch
):
    from legal_radar.adapters.assayer import harness as assayer_harness

    monkeypatch.setattr(assayer_harness, "CHECKPOINT_DIR", tmp_path)
    questions = [Question("one", "q1", (A,), (A,))]
    answer = CitedAnswer("q1", "x", "ok", [], [])

    assayer_harness.checkpoint_for(System("rag-naive", 5), questions, "p1").save(
        "one", answer, (1, 1)
    )

    assert assayer_harness.checkpoint_for(System("rag-naive", 5), questions, "p1").done.keys() == {
        "one"
    }
    assert (
        assayer_harness.checkpoint_for(System("rag-naive", 15), questions, "p1").done == {}
    )  # own file
    changed = [Question("one", "other wording", (A,), (A,))]
    assert assayer_harness.checkpoint_for(System("rag-naive", 5), changed, "p1").done == {}
    assayer_harness.checkpoint_for(System("rag-naive", 5), questions, "p1").save(
        "one", answer, (1, 1)
    )
    assert assayer_harness.checkpoint_for(System("rag-naive", 5), questions, "p2").done == {}


def test_a_failing_publish_does_not_fail_the_run_and_hears_the_result():
    meter = UsageMeter(FakeProvider())
    heard = []

    def publish(result):
        heard.append(result)
        raise RuntimeError("langsmith down")

    def ask(query: str) -> CitedAnswer:
        return CitedAnswer(query, "x", "ok", [], [A])

    report = run_evaluation(
        [Question("one", "q", (A,), (A,))], ask, meter, lambda a: False, publish=publish
    )
    assert len(report.questions) == 1 and len(heard) == 1
