"""Runs the evaluation under the `assayer` library (`uv sync --extra eval`): its `Runner`
orchestrates the questions and keeps their tokens; the custom metrics come from
`legal_radar.application.evaluation.answers` and the flat grounding metric from RAGAS (imported
lazily). Only the CLI and the tests import this module, so the rest of the package runs without
the `eval` extra."""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from assayer.metrics import Detailed, Metric
from assayer.models import (
    Case,
    Dataset,
    Experiment,
    PricingConfig,
    Score,
    Step,
    TokenUsage,
    Trajectory,
)
from assayer.runner import Runner

from legal_radar.adapters.tracing import safely
from legal_radar.application.answer import CitedAnswer
from legal_radar.application.evaluation.answers import (
    BASE_LEVEL,
    Checkpoint,
    Question,
    System,
    UsageMeter,
    abstention,
    citation_correctness,
    contradiction_surfaced,
    graph_path,
    outcome_of,
)
from legal_radar.domain.llm import content_hash
from legal_radar.settings import Settings

RUNS_DIR = Settings().runs_dir
CITATIONS, PATH, CONTRADICTIONS = "citation_check", "path", "contradiction_check"
ABSTENTION = "abstention_check"
MENTIONS = "mentions_check"


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens; free tiers cost nothing, so the default is zero."""

    input: float = 0.0
    output: float = 0.0


@dataclass
class Report:
    experiment: str
    scores: dict[str, float | None]  # metric -> mean over the questions it applies to
    questions: list[dict]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    prompt_snapshot: str | None = None
    grounding: dict = field(default_factory=dict)
    system: str = "graph"  # what answered: the graph, or a RAG baseline (`rag-naive`, ...)
    k: int | None = None  # the baseline's top-k; None for the graph
    by_level: dict[str, dict[str, float | None]] = field(default_factory=dict)  # level -> scores

    def _persisted(self) -> dict:
        """The run file keeps the Portuguese key `by_nivel`, so earlier runs stay comparable."""
        raw = dict(self.__dict__)
        raw["by_nivel"] = raw.pop("by_level")
        return raw

    def render(self) -> str:
        label = System(self.system, self.k).label
        lines = [f"experiment {self.experiment} [{label}]: {len(self.questions)} questions"]
        for name, value in {**self.scores, **self.grounding}.items():
            shown = f"{value:.3f}" if isinstance(value, float) else value
            lines.append(f"  {name}: {'n/a' if value is None else shown}")
        lines.append(
            f"  tokens: {self.input_tokens} in, {self.output_tokens} out; "
            f"cost: ${self.cost_usd:.4f} (zero unless --price-in/--price-out are set; "
            "RAGAS judge calls are not counted; the totals include the contradiction judge, "
            "which the per-question tokens do not)"
        )
        return "\n".join(lines)

    def write(self, directory: Path = RUNS_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.experiment}.json"
        path.write_text(
            json.dumps(self._persisted(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path


def build_metrics(
    flags_contradiction: Callable[[str], bool],
    states_insufficient: Callable[[str], bool] = lambda answer: False,
) -> dict[str, Metric]:
    """The field map of the evaluation: each output field with the assayer metric that scores it.
    A metric that returns None does not apply to the question: no score, and no failure."""

    def citation(trajectory, case):
        reference = case.expected_output
        if not reference["expected"]:  # an abstain question
            return None
        prediction = trajectory.final_output
        score = citation_correctness(
            prediction["cited"],
            prediction["retrieved"],
            reference["expected"],
            reference["also_ok"],
        )
        return Detailed(
            score.f1,
            metadata={
                "precision": score.precision,
                "recall": score.recall,
                "fabricated": score.fabricated,
            },
        )

    def path(trajectory, case):
        if not case.expected_output:
            return None
        score = graph_path(set(trajectory.final_output), set(case.expected_output))
        return Detailed(score.f1, metadata={"precision": score.precision, "recall": score.recall})

    def contradiction(trajectory, case):
        prediction = trajectory.final_output
        return contradiction_surfaced(
            prediction["answer"],
            prediction["cited"],
            [tuple(pair) for pair in case.expected_output],
            flags_contradiction,
        )

    def abstains(trajectory, case):
        return abstention(
            trajectory.final_output["answer"], bool(case.expected_output), states_insufficient
        )

    def mentions(trajectory, case):
        """1.0 when every article the answer names was among its sources, else 0.0."""
        unsupported = list(trajectory.final_output)
        return Detailed(0.0 if unsupported else 1.0, metadata={"unsupported": unsupported})

    return {
        CITATIONS: Metric("citation_correctness", "trajectory", citation),
        PATH: Metric("graph_path", "trajectory", path),
        CONTRADICTIONS: Metric("contradiction_surfaced", "trajectory", contradiction),
        ABSTENTION: Metric("abstention", "trajectory", abstains),
        MENTIONS: Metric("grounded_mentions", "trajectory", mentions),
    }


def _import_ragas() -> None:
    """ragas 0.4 imports `ChatVertexAI`, which langchain-community 0.4 dropped; stub that one
    module so ragas imports (we never use Vertex)."""
    import sys
    import types

    name = "langchain_community.chat_models.vertexai"
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            stub = types.ModuleType(name)
            stub.ChatVertexAI = type("ChatVertexAI", (), {})
            sys.modules[name] = stub


def ragas_faithfulness(rows: list[dict], llm) -> list[float]:
    """RAGAS `Faithfulness` per row (`user_input`, `response`, `retrieved_contexts`): the share of
    the answer's claims its contexts support. `llm` is a RAGAS-compatible judge model."""
    _import_ragas()
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import Faithfulness

    result = evaluate(EvaluationDataset.from_list(rows), metrics=[Faithfulness()], llm=llm)
    scores = [float(row["faithfulness"]) for row in result.scores]
    return [score for score in scores if score == score]  # RAGAS reports a failed judge as nan


def aggregate(scores: Iterable[Score], graph_paths: bool = True) -> dict[str, float | None]:
    """Mean per metric over the questions it applies to: the metric's score (F1 for the set
    metrics), its precision and recall, and the fabricated citations per question."""
    values: dict[str, list[float]] = {}
    for score in scores:
        if score.field is None:
            continue
        values.setdefault(score.name, []).append(score.value)
        for key in ("precision", "recall"):
            if key in score.metadata:
                values.setdefault(f"{score.name}_{key}", []).append(score.metadata[key])
        if "fabricated" in score.metadata:
            values.setdefault("fabricated_citations", []).append(len(score.metadata["fabricated"]))
    result: dict[str, float | None] = {k: sum(v) / len(v) for k, v in values.items()}
    result.setdefault("contradiction_surfaced", None)  # no question labeled a contradiction
    result.setdefault("abstention", None)  # no question the graph cannot answer
    if not graph_paths:
        result["graph_path"] = None  # not applicable: there is no graph to walk
    return result


CHECKPOINT_DIR = RUNS_DIR / "checkpoints"


def checkpoint_for(
    system: System, questions: list[Question], prompt_snapshot: str | None
) -> Checkpoint:
    """The checkpoint of the run of `system` over `questions`: one file per system, valid only
    while the questions and the pinned prompts are the same."""
    fingerprint = content_hash(
        {"prompts": prompt_snapshot, "questions": [(q.id, q.query) for q in questions]}
    )
    return Checkpoint(CHECKPOINT_DIR / f"{system.slug}.json", fingerprint)


def aggregate_by_level(
    scores: Iterable[Score], level_of: dict[str, str | None], graph_paths: bool = True
) -> dict[str, dict]:
    """`aggregate` over the questions of each `nivel` (`level_of` maps a question id to it)."""
    groups: dict[str, list[Score]] = {}
    for score in scores:
        groups.setdefault(level_of.get(score.target_id) or BASE_LEVEL, []).append(score)
    return {level: aggregate(group, graph_paths) for level, group in sorted(groups.items())}


def run_evaluation(
    questions: list[Question],
    ask: Callable[[str], CitedAnswer],
    meter: UsageMeter,
    flags_contradiction: Callable[[str], bool],
    states_insufficient: Callable[[str], bool] = lambda answer: False,
    *,
    pricing: Pricing | None = None,
    grounding_llm=None,
    prompt_snapshot: str | None = None,
    experiment: str | None = None,
    system: System | None = None,
    checkpoint: Checkpoint | None = None,
    publish: Callable[[Experiment], None] | None = None,
) -> Report:
    """Answers every question through `ask` (whose model calls go through `meter`) and scores it.
    A `checkpoint` keeps each answer as it arrives, so a run that dies resumes without asking
    again (the caller discards it once the report is written). A system with no graph (a RAG
    baseline) leaves `graph_path` unscored: n/a. `publish`, when given, hears of the assayer
    Experiment (to trace it in LangSmith); it never fails the run."""
    price = pricing or Pricing()
    system = system or System()

    by_id = {q.id: q for q in questions}
    died: list[BaseException] = []  # assayer keeps a target's exception as data: raise it again

    def target(question_id: str) -> Trajectory:
        if died:  # the run is lost: do not spend tokens on the questions after it
            raise died[0]
        try:
            if checkpoint and question_id in checkpoint.done:  # answered before a crash
                answer, usage = checkpoint.done[question_id]
                meter.total_input += usage[0]
                meter.total_output += usage[1]
            else:
                meter.reset()
                answer = ask(by_id[question_id].query)
                usage = meter.usage
                if checkpoint:
                    checkpoint.save(question_id, answer, usage)
        except Exception as error:
            died.append(error)
            raise
        return Trajectory(
            steps=[
                Step(
                    "model",
                    input=by_id[question_id].query,
                    output=answer.answer,
                    usage=TokenUsage(usage[0], usage[1], None),
                )
            ],
            final_output=outcome_of(answer),
        )

    metrics = build_metrics(flags_contradiction, states_insufficient)
    if not system.has_graph:
        del metrics[PATH]
    name = experiment or datetime.now(UTC).strftime("eval-%Y%m%dT%H%M%S%fZ")
    dataset = Dataset(
        name,
        [
            Case(
                input=q.id,
                id=q.id,
                expected_output={
                    CITATIONS: {"expected": list(q.citations), "also_ok": list(q.also_ok)},
                    **({PATH: list(q.nodes)} if system.has_graph else {}),
                    CONTRADICTIONS: [list(pair) for pair in q.contradictions],
                    ABSTENTION: q.abstain,
                    MENTIONS: [],
                },
            )
            for q in questions
        ],
    )
    result = Runner(
        target,
        field_metrics={path: [metric] for path, metric in metrics.items()},
        pricing=PricingConfig(price.input / 1e6, price.output / 1e6),
    ).run(dataset)
    if died:
        raise died[0]
    if result.failures:  # a judge that fails is a lost score, not a score of zero
        raise RuntimeError(
            "metrics failed: " + "; ".join(f"{f.metric}: {f.error}" for f in result.failures)
        )
    if publish is not None:
        safely(lambda: publish(result))

    trajectories = {t.case_id: t for t in result.trajectories}
    grounding = {}
    if grounding_llm is not None:
        rows = [
            {
                "user_input": by_id[case_id].query,
                "response": t.final_output["answer"],
                "retrieved_contexts": list(t.final_output["sources"].values()),
            }
            for case_id, t in trajectories.items()
            if t.final_output["answer"] and t.final_output["sources"]
        ]
        faithfulness = ragas_faithfulness(rows, grounding_llm)
        grounding["faithfulness"] = sum(faithfulness) / len(faithfulness) if faithfulness else None
        grounding["faithfulness_scored"] = f"{len(faithfulness)}/{len(rows)}"
    level_of = {q.id: q.level for q in questions}
    return Report(
        name,
        aggregate(result.scores, system.has_graph),
        [
            {
                "id": case_id,
                "nivel": level_of.get(case_id),
                "answer": t.final_output["answer"],
                "citations": t.final_output["citations"],
                "citation_paths": t.final_output.get("citation_paths", {}),
                "scores": {
                    s.name: s.value
                    for s in result.scores
                    if s.target_id == case_id and s.field is not None
                },
                "input_tokens": t.total_usage().input_tokens,
                "output_tokens": t.total_usage().output_tokens,
            }
            for case_id, t in trajectories.items()
        ],
        meter.total_input,  # the answers plus the contradiction judge, unlike the per-question rows
        meter.total_output,
        (meter.total_input * price.input + meter.total_output * price.output) / 1e6,
        prompt_snapshot,
        grounding,
        system.name,
        system.k,
        aggregate_by_level(result.scores, level_of, system.has_graph),
    )


def ragas_llm_from_env():
    """The RAGAS judge model, any OpenAI-compatible endpoint (e.g. LM Studio or Groq):
    RAGAS_BASE_URL, RAGAS_MODEL and optionally RAGAS_API_KEY."""
    import os

    from openai import OpenAI

    _import_ragas()
    from ragas.llms import llm_factory

    client = OpenAI(
        base_url=os.environ["RAGAS_BASE_URL"], api_key=os.environ.get("RAGAS_API_KEY", "none")
    )
    return llm_factory(os.environ["RAGAS_MODEL"], client=client)
