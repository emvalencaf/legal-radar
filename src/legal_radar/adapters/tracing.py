"""Optional LangSmith tracing of query-time (the LangGraph run) and evaluation (assayer's
experiment). Off without credentials, and a failed trace never fails the run. Ingestion and
enrichment never call this: they stay on wide events (ADR-0004)."""

import json
import logging
import os
from collections.abc import Callable, MutableMapping
from datetime import UTC, datetime
from uuid import uuid4

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
    """Publishes an assayer experiment to LangSmith: one run per question, under the project
    `dataset`, with each evaluation as feedback on it. (assayer's own publisher calls an older
    `Client.create_run` signature, so it is not used.)"""

    def __init__(self, client):
        self.client = client

    def publish(self, result, dataset: str) -> None:
        now = datetime.now(UTC)
        runs = []
        for run in result.runs:
            run_id = uuid4()
            self.client.create_run(
                id=run_id,
                name=result.experiment_name,
                run_type="chain",
                inputs={"question": run.input},
                outputs=run.output,
                project_name=dataset,
                start_time=now,
                end_time=now,
                extra={
                    "metadata": {
                        "input_tokens": run.token_usage.input_tokens,
                        "output_tokens": run.token_usage.output_tokens,
                    }
                },
            )
            runs.append((run_id, run))
        self.client.flush()  # the runs must exist before feedback refers to them
        for run_id, run in runs:
            for e in run.evaluations:
                self.client.create_feedback(
                    run_id,
                    f"{e.field_name}/{e.evaluator_method}",
                    score=e.score,
                    comment=json.dumps(e.metadata, default=str),
                )
        self.client.flush()


def publisher_if_enabled(env: MutableMapping[str, str] | None = None):
    """The experiment publisher when tracing is on (needs `langsmith`), else None."""
    if not configure_tracing(env):
        return None
    import langsmith

    return ExperimentPublisher(langsmith.Client())


def safely(action: Callable[[], None]) -> None:
    """Runs a tracing step; an outage is logged and the run goes on."""
    try:
        action()
    except Exception as error:  # tracing is optional: whatever it raises
        log.warning("LangSmith tracing failed, continuing without it: %s", error)
