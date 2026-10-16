"""Runs the answer evaluation over one or more systems (the graph, RAG baselines), each with its
own checkpoint so an interrupted run resumes. The CLI only builds the systems and prints."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from legal_radar.adapters.tracing import DATASET
from legal_radar.answer_evaluation import (
    Question,
    System,
    UsageMeter,
    llm_flags_contradiction,
    llm_states_insufficiency,
)
from legal_radar.application.answer import CitedAnswer
from legal_radar.assayer_harness import (
    RUNS_DIR,
    Pricing,
    Report,
    checkpoint_for,
    run_evaluation,
)
from legal_radar.domain.prompts import PromptLock


def run_systems(
    systems: list[tuple[System, Callable[[str], CitedAnswer]]],
    questions: list[Question],
    meter: UsageMeter,
    lock: PromptLock,
    *,
    pricing: Pricing | None = None,
    grounding_llm=None,
    fresh: bool = False,
    runs_dir: Path = RUNS_DIR,
    on_report: Callable[[Report, Path], None] = lambda report, path: None,
    on_resume: Callable[[System, int], None] = lambda system, answered: None,
    publisher=None,
) -> list[Report]:
    """Scores each `(system, ask)` over `questions` in turn. A run that dies resumes next time
    from its saved answers (`fresh` discards them); the checkpoint is dropped once the report is
    written (to `runs_dir`), and `on_report` hears of each report and its file as soon as it is.
    A LangSmith `publisher` (see `tracing`) gets each experiment's result."""
    publish = (lambda result: publisher.publish(result, DATASET)) if publisher else None
    reports = []
    for system, ask in systems:
        checkpoint = checkpoint_for(system, questions, lock.snapshot_hash)
        if fresh:
            checkpoint.discard()
            checkpoint = checkpoint_for(system, questions, lock.snapshot_hash)
        if checkpoint.done:
            on_resume(system, len(checkpoint.done))
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        report = run_evaluation(
            questions,
            ask,
            meter,
            llm_flags_contradiction(meter),
            llm_states_insufficiency(meter),
            pricing=pricing,
            grounding_llm=grounding_llm,
            prompt_snapshot=lock.snapshot_hash,
            experiment=f"{system.slug}-{stamp}",
            system=system,
            checkpoint=checkpoint,
            publish=publish,
        )
        on_report(report, report.write(runs_dir))
        checkpoint.discard()
        reports.append(report)
    return reports
