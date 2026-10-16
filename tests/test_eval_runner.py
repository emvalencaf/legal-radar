import pytest

pytest.importorskip("assayer")  # the `eval` extra

from legal_radar import assayer_harness
from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.answer import Citation, CitedAnswer
from legal_radar.answer_evaluation import Question, System, UsageMeter
from legal_radar.eval_runner import run_systems
from legal_radar.prompts import PromptLock

A = "lei#a"
QUESTIONS = [Question("one", "q1", (A,), (A,)), Question("two", "q2", (A,), (A,))]


class Lock(PromptLock):
    def __init__(self):
        pass

    snapshot_hash = "snap"


def answering(asked):
    def ask(query):
        asked.append(query)
        return CitedAnswer(query, "x", "ok", [Citation(A, "Dispositivo", [], "t")], [A])

    return ask


@pytest.fixture(autouse=True)
def checkpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(assayer_harness, "CHECKPOINT_DIR", tmp_path / "ck")


def run(tmp_path, systems, **kwargs):
    seen = []
    reports = run_systems(
        systems,
        QUESTIONS,
        UsageMeter(FakeProvider()),
        Lock(),
        runs_dir=tmp_path / "runs",
        on_report=lambda report, path: seen.append((report.experiment, path)),
        **kwargs,
    )
    return reports, seen


def test_each_system_is_scored_written_and_named_after_its_slug(tmp_path):
    asked = []
    systems = [(System(), answering(asked)), (System("rag-naive", 5), answering(asked))]

    reports, seen = run(tmp_path, systems)

    assert [(r.system, r.k) for r in reports] == [("graph", None), ("rag-naive", 5)]
    assert reports[0].scores["graph_path"] is not None and reports[1].scores["graph_path"] is None
    assert [name.rsplit("-", 1)[0] for name, _ in seen] == ["graph", "rag-naive-k5"]
    assert all(path.exists() for _, path in seen)
    assert not list((tmp_path / "ck").glob("*.json"))  # checkpoints go once the report is written


def test_a_system_that_dies_resumes_and_fresh_starts_over(tmp_path):
    asked, resumed = [], []
    boom = {"q2"}

    def flaky(query):
        if query in boom:
            raise RuntimeError("network down")
        return answering(asked)(query)

    with pytest.raises(RuntimeError):
        run(tmp_path, [(System(), flaky)])
    boom.clear()

    run(
        tmp_path, [(System(), flaky)], on_resume=lambda system, n: resumed.append((system.label, n))
    )
    assert asked == ["q1", "q2"] and resumed == [("graph", 1)]  # q1 was not asked again

    asked.clear()
    with pytest.raises(RuntimeError):
        boom.add("q2")
        run(tmp_path, [(System(), flaky)])
    boom.clear()
    run(tmp_path, [(System(), flaky)], fresh=True)
    assert asked == ["q1", "q1", "q2"]  # fresh: q1 asked again


def test_a_publisher_hears_each_experiment_under_the_eval_dataset(tmp_path):
    class Publisher:
        def __init__(self):
            self.heard = []

        def publish(self, result, dataset):
            self.heard.append((result.experiment_name, dataset))

    publisher = Publisher()
    reports, _ = run(tmp_path, [(System(), answering([]))], publisher=publisher)

    assert publisher.heard == [(reports[0].experiment, "legal-radar-eval")]
