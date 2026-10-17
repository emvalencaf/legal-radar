"""Optional LangSmith tracing of query-time (the LangGraph run) and evaluation (assayer's
experiment). Off without credentials, and a failed trace never fails the run. Ingestion and
enrichment never call this: they stay on wide events (ADR-0004)."""

import logging
import os
from collections.abc import Callable, MutableMapping

log = logging.getLogger(__name__)

API_KEY_VARS = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")
DATASET = "legal-radar-eval"


def configure_tracing(env: MutableMapping[str, str] | None = None) -> bool:
    """Switches LangGraph's LangSmith tracing on when a key is set (unless `LANGSMITH_TRACING` is
    `false`) and off otherwise; returns whether it is on. Call it before building the graph."""
    env = os.environ if env is None else env
    on = (
        any(env.get(key) for key in API_KEY_VARS)
        and env.get("LANGSMITH_TRACING", "").lower() != "false"
    )
    env["LANGSMITH_TRACING"] = "true" if on else "false"
    return on


class ExperimentPublisher:
    """Publishes an assayer Experiment to LangSmith through assayer's `LangSmithAdapter`: the
    questions become examples of the dataset `DATASET`, the experiment a project of its own, each
    answer a run tree and each score feedback on it."""

    def __init__(self, adapter):
        self.adapter = adapter

    def publish(self, experiment) -> None:
        report = self.adapter.export(experiment)
        if not report.ok:  # the adapter reports what failed instead of raising
            log.warning(
                "LangSmith export incomplete: %d failed, %d skipped",
                len(report.failed),
                len(report.skipped),
            )


def publisher_if_enabled(env: MutableMapping[str, str] | None = None):
    """The experiment publisher when tracing is on (needs the `eval` extra), else None."""
    if not configure_tracing(env):
        return None
    from assayer.adapters import LangSmithAdapter

    return ExperimentPublisher(LangSmithAdapter(dataset_name=DATASET))


def safely(action: Callable[[], None]) -> None:
    """Runs a tracing step; an outage is logged and the run goes on."""
    try:
        action()
    except Exception as error:  # tracing is optional: whatever it raises
        log.warning("LangSmith tracing failed, continuing without it: %s", error)
