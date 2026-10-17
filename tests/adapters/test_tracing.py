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


def test_the_experiment_goes_through_the_adapter_and_an_incomplete_export_is_only_logged(caplog):
    from types import SimpleNamespace as Ns

    from legal_radar.adapters.tracing import ExperimentPublisher

    exported = []

    class Adapter:
        def export(self, experiment):
            exported.append(experiment)
            return Ns(ok=False, failed=["a"], skipped=[])

    with caplog.at_level(logging.WARNING):
        ExperimentPublisher(Adapter()).publish("experiment")

    assert exported == ["experiment"] and "1 failed" in caplog.text
