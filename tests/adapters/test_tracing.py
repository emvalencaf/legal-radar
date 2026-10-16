import logging

from legal_radar.adapters.tracing import configure_tracing, publisher_if_enabled, safely


def test_without_a_key_tracing_is_switched_off_even_if_asked_for():
    env = {"LANGSMITH_TRACING": "true"}
    assert configure_tracing(env) is False
    assert env["LANGSMITH_TRACING"] == "false"


def test_with_a_key_tracing_is_switched_on():
    env = {"LANGSMITH_API_KEY": "k"}
    assert configure_tracing(env) is True
    assert env["LANGSMITH_TRACING"] == "true"


def test_an_explicit_opt_out_wins_over_the_key():
    env = {"LANGSMITH_API_KEY": "k", "LANGSMITH_TRACING": "false"}
    assert configure_tracing(env) is False
    assert env["LANGSMITH_TRACING"] == "false"


def test_the_legacy_key_name_counts():
    assert configure_tracing({"LANGCHAIN_API_KEY": "k"}) is True


def test_no_publisher_without_credentials():
    assert publisher_if_enabled({}) is None


def test_a_failing_trace_publish_is_logged_and_never_raised(caplog):
    def boom():
        raise RuntimeError("network down")

    with caplog.at_level(logging.WARNING):
        safely(boom)
    assert "network down" in caplog.text


def test_the_experiment_is_published_as_runs_with_feedback_after_a_flush():
    from types import SimpleNamespace as Ns

    from legal_radar.adapters.tracing import ExperimentPublisher

    calls = []

    class Client:
        def create_run(self, **kw):
            calls.append(("run", kw))

        def flush(self):
            calls.append(("flush", None))

        def create_feedback(self, run_id, key, **kw):
            calls.append(("feedback", (run_id, key, kw["score"])))

    evaluation = Ns(field_name="citation_check", evaluator_method="citation_correctness",
                    score=0.5, metadata={"precision": 1})  # fmt: skip
    run = Ns(input="q1", output={"answer": "a"}, evaluations=[evaluation],
             token_usage=Ns(input_tokens=3, output_tokens=2))  # fmt: skip
    ExperimentPublisher(Client()).publish(Ns(experiment_name="graph-1", runs=[run]), "proj")

    kinds = [kind for kind, _ in calls]
    assert kinds == ["run", "flush", "feedback", "flush"]
    run_call, feedback = calls[0][1], calls[2][1]
    assert run_call["project_name"] == "proj" and run_call["run_type"] == "chain"
    assert feedback == (run_call["id"], "citation_check/citation_correctness", 0.5)
