"""Runs the evaluation under the `assayer` harness (`uv sync --extra eval`): it orchestrates the
questions and counts tokens and cost per run; the custom metrics come from
`legal_radar.answer_evaluation` and the flat grounding metric from RAGAS. Both libraries are
imported lazily so the rest of the package runs without them."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from legal_radar.answer import CitedAnswer
from legal_radar.answer_evaluation import (
    Checkpoint,
    Outcome,
    Question,
    System,
    UsageMeter,
    abstention,
    citation_correctness,
    contradiction_surfaced,
    graph_path,
    outcome_of,
)
from legal_radar.llm import content_hash
from legal_radar.tracing import safely

RUNS_DIR = Path(__file__).resolve().parents[2] / "eval-runs"
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
    by_nivel: dict[str, dict[str, float | None]] = field(default_factory=dict)  # nivel -> scores

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
            json.dumps(self.__dict__, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return path


def build_registries(
    flags_contradiction: Callable[[str], bool],
    states_insufficient: Callable[[str], bool] = lambda answer: False,
):
    """assayer evaluator and metric registries holding the three custom evaluators."""
    from assayer.evaluators.base import BaseEvaluator
    from assayer.models import FieldEvaluation
    from assayer.registries import EvaluatorRegistry, MetricRegistry

    class CitationEvaluator(BaseEvaluator):
        def evaluate(self, prediction, reference, **kwargs):
            score = citation_correctness(
                prediction["cited"],
                prediction["retrieved"],
                reference["expected"],
                reference["also_ok"],
            )
            return FieldEvaluation(
                CITATIONS, "citation_correctness", reference, prediction["cited"], score.f1, None,
                {
                    "precision": score.precision,
                    "recall": score.recall,
                    "fabricated": score.fabricated,
                    "applicable": bool(reference["expected"]),  # none: an abstain question
                },
            )  # fmt: skip

    class PathEvaluator(BaseEvaluator):
        def evaluate(self, prediction, reference, **kwargs):
            score = graph_path(set(prediction), set(reference))
            return FieldEvaluation(
                PATH, "graph_path", reference, prediction, score.f1, None,
                {
                    "precision": score.precision,
                    "recall": score.recall,
                    "applicable": bool(reference),
                },
            )  # fmt: skip

    class ContradictionEvaluator(BaseEvaluator):
        def evaluate(self, prediction, reference, **kwargs):
            surfaced = contradiction_surfaced(
                prediction["answer"],
                prediction["cited"],
                [tuple(pair) for pair in reference],
                flags_contradiction,
            )
            return FieldEvaluation(
                CONTRADICTIONS, "contradiction_surfaced", reference, prediction["cited"],
                surfaced or 0.0, None, {"applicable": surfaced is not None},
            )  # fmt: skip

    class AbstentionEvaluator(BaseEvaluator):
        def evaluate(self, prediction, reference, **kwargs):
            score = abstention(prediction["answer"], bool(reference), states_insufficient)
            return FieldEvaluation(
                ABSTENTION, "abstention", reference, prediction["answer"], score or 0.0, None,
                {"applicable": score is not None},
            )  # fmt: skip

    class MentionsEvaluator(BaseEvaluator):
        def evaluate(self, prediction, reference, **kwargs):
            """1.0 when every article the answer names was among its sources, else 0.0."""
            return FieldEvaluation(
                MENTIONS, "grounded_mentions", reference, prediction,
                0.0 if prediction else 1.0, None, {"unsupported": list(prediction)},
            )  # fmt: skip

    evaluators = EvaluatorRegistry()
    evaluators.register("citation_correctness", CitationEvaluator)
    evaluators.register("graph_path", PathEvaluator)
    evaluators.register("contradiction_surfaced", ContradictionEvaluator)
    evaluators.register("abstention", AbstentionEvaluator)
    evaluators.register("grounded_mentions", MentionsEvaluator)
    return evaluators, MetricRegistry()


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


def aggregate(runs, graph_paths: bool = True) -> dict[str, float | None]:
    """Mean per metric over the questions it applies to: the evaluator's score (F1 for the set
    metrics), its precision and recall, and the fabricated citations per question."""
    values: dict[str, list[float]] = {}
    for run in runs:
        for e in run.evaluations:
            if e.metadata.get("applicable") is False:
                continue
            values.setdefault(e.evaluator_method, []).append(e.score)
            for key in ("precision", "recall"):
                if key in e.metadata:
                    values.setdefault(f"{e.evaluator_method}_{key}", []).append(e.metadata[key])
            if "fabricated" in e.metadata:
                values.setdefault("fabricated_citations", []).append(len(e.metadata["fabricated"]))
    scores: dict[str, float | None] = {k: sum(v) / len(v) for k, v in values.items()}
    scores.setdefault("contradiction_surfaced", None)  # no question labeled a contradiction
    scores.setdefault("abstention", None)  # no question the graph cannot answer
    if not graph_paths:
        scores["graph_path"] = None  # not applicable: there is no graph to walk
    return scores


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


BASE_NIVEL = "base"  # the questions that carry no `nivel`


def aggregate_by_nivel(
    runs, nivel_of: dict[str, str | None], graph_paths: bool = True
) -> dict[str, dict]:
    """`aggregate` over the questions of each `nivel` (`nivel_of` maps a question id to it)."""
    groups: dict[str, list] = {}
    for run in runs:
        groups.setdefault(nivel_of.get(run.input) or BASE_NIVEL, []).append(run)
    return {nivel: aggregate(group, graph_paths) for nivel, group in sorted(groups.items())}


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
    publish: Callable[[object], None] | None = None,
) -> Report:
    """Answers every question through `ask` (whose model calls go through `meter`) and scores it.
    A `checkpoint` keeps each answer as it arrives, so a run that dies resumes without asking
    again (the caller discards it once the report is written). A system with no graph (a RAG
    baseline) leaves `graph_path` unscored: n/a. `publish`, when given, hears of the experiment's
    result (to trace it in LangSmith); it never fails the run."""
    from assayer.runner.pipeline import EvaluationPipeline
    from assayer.runner.pricing import PricingConfig

    price = pricing or Pricing()
    system = system or System()

    by_id = {q.id: q for q in questions}

    def target(question_id: str) -> Outcome:
        if (
            checkpoint and question_id in checkpoint.done
        ):  # answered before a crash: not asked again
            answer, usage = checkpoint.done[question_id]
            meter.total_input += usage[0]
            meter.total_output += usage[1]
            return outcome_of(answer, usage)
        meter.reset()
        answer = ask(by_id[question_id].query)
        if checkpoint:
            checkpoint.save(question_id, answer, meter.usage)
        return outcome_of(answer, meter.usage)

    dataset = [
        {
            "input": q.id,
            "expected_output": {
                CITATIONS: {"expected": list(q.citations), "also_ok": list(q.also_ok)},
                **({PATH: list(q.nodes)} if system.has_graph else {}),
                CONTRADICTIONS: [list(pair) for pair in q.contradictions],
                ABSTENTION: q.abstain,
                MENTIONS: [],
            },
        }
        for q in questions
    ]
    evaluators, metrics = build_registries(flags_contradiction, states_insufficient)
    name = experiment or datetime.now(UTC).strftime("eval-%Y%m%dT%H%M%S%fZ")
    result = EvaluationPipeline(
        target_fn=target,
        dataset=dataset,
        field_evaluators={
            CITATIONS: ["citation_correctness"],
            **({PATH: ["graph_path"]} if system.has_graph else {}),
            CONTRADICTIONS: ["contradiction_surfaced"],
            ABSTENTION: ["abstention"],
            MENTIONS: ["grounded_mentions"],
        },
        metrics=[],
        evaluator_registry=evaluators,
        metric_registry=metrics,
        pricing_config=PricingConfig(price.input / 1e6, price.output / 1e6),
        experiment_name=name,
    ).run()
    if publish is not None:
        safely(lambda: publish(result))

    grounding = {}
    if grounding_llm is not None:
        rows = [
            {
                "user_input": by_id[run.input].query,
                "response": run.output["answer"],
                "retrieved_contexts": list(run.output["sources"].values()),
            }
            for run in result.runs
            if run.output["answer"] and run.output["sources"]
        ]
        faithfulness = ragas_faithfulness(rows, grounding_llm)
        grounding["faithfulness"] = sum(faithfulness) / len(faithfulness) if faithfulness else None
        grounding["faithfulness_scored"] = f"{len(faithfulness)}/{len(rows)}"
    nivel_of = {q.id: q.nivel for q in questions}
    return Report(
        name,
        aggregate(result.runs, system.has_graph),
        [
            {
                "id": run.input,
                "nivel": nivel_of.get(run.input),
                "answer": run.output["answer"],
                "citations": run.output["citations"],
                "scores": {
                    e.evaluator_method: e.score
                    for e in run.evaluations
                    if e.metadata.get("applicable") is not False
                },
                "input_tokens": run.token_usage.input_tokens,
                "output_tokens": run.token_usage.output_tokens,
            }
            for run in result.runs
        ],
        meter.total_input,  # the answers plus the contradiction judge, unlike the per-question rows
        meter.total_output,
        (meter.total_input * price.input + meter.total_output * price.output) / 1e6,
        prompt_snapshot,
        grounding,
        system.name,
        system.k,
        aggregate_by_nivel(result.runs, nivel_of, system.has_graph),
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
