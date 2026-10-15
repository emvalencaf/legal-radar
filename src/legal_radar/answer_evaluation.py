"""Evaluation of the cited-answer pipeline over a question set.

The custom metrics (citation correctness, contradiction surfacing, graph path) are pure functions
over ids, so they are tested table-driven; `legal_radar.assayer_harness` runs them, with the flat
grounding metrics from RAGAS, under the `assayer` harness."""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from legal_radar.answer import Citation, CitedAnswer
from legal_radar.llm import Completion, CompletionParams, Embedding
from legal_radar.ports import Provider

QUESTIONS_DIR = Path(__file__).resolve().parents[2] / "evals"
QUESTION_PATHS = {
    "desconsideração da personalidade jurídica": QUESTIONS_DIR / "desconsideracao_personalidade.yml"
}


@dataclass(frozen=True)
class Question:
    id: str
    query: str
    citations: tuple[str, ...]  # ids a correct answer cites
    nodes: tuple[str, ...]  # nodes the traversal should walk through to reach those citations
    contradictions: tuple[tuple[str, str], ...] = ()  # cited sources that disagree: flag it
    abstain: bool = False  # the graph cannot answer it: a good answer says so, citing nothing
    also_ok: tuple[str, ...] = ()  # sources a good answer may cite too: not required, not an error
    nivel: str | None = None  # facil | medio | dificil | armadilha; None for the base questions


@dataclass(frozen=True)
class SetScore:
    precision: float
    recall: float

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


@dataclass(frozen=True)
class CitationScore(SetScore):
    fabricated: list[str]  # cited ids the traversal never retrieved


def load_questions(path: Path) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [
        Question(
            q["id"],
            q["query"],
            tuple(q.get("citations", ())),
            tuple(q.get("nodes", ())),
            tuple((a, b) for a, b in q.get("contradictions", [])),
            bool(q.get("abstain", False)),
            tuple(q.get("also_ok", ())),
            q.get("nivel"),
        )
        for q in raw["questions"]
    ]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate question ids")
    for q in questions:
        if q.abstain and (q.citations or q.nodes or q.contradictions or q.also_ok):
            raise ValueError(
                f"{path}: {q.id} abstains, so it can expect no citation, node or also_ok"
            )
        if not q.abstain and not q.citations:
            raise ValueError(f"{path}: {q.id} expects no citation: mark it `abstain: true`")
    return questions


def _precision_recall(found: set[str], expected: set[str]) -> tuple[float, float]:
    hits = len(found & expected)
    precision = hits / len(found) if found else float(not expected)
    recall = hits / len(expected) if expected else 1.0
    return precision, recall


def citation_correctness(
    cited: Iterable[str],
    retrieved: Iterable[str],
    expected: Iterable[str],
    also_ok: Iterable[str] = (),
) -> CitationScore:
    """Precision: the cited ids that were expected. Recall: the expected ids that were cited.
    An `also_ok` id is neither required nor an error: it leaves precision alone when cited and
    recall alone when not. `fabricated` lists the cited ids outside what was retrieved (the
    schema should forbid them)."""
    cited, expected = list(cited), set(expected)
    tolerated = set(also_ok) - expected
    precision, recall = _precision_recall(set(cited) - tolerated, expected)
    known = set(retrieved)
    return CitationScore(precision, recall, [i for i in cited if i not in known])


def graph_path(found: set[str], expected: set[str]) -> SetScore:
    """Precision and recall of the nodes the answer's traversal paths cross vs the expected ones."""
    return SetScore(*_precision_recall(found, expected))


def path_nodes(citations: Iterable[Citation]) -> set[str]:
    """Every cited node, plus each node a hop on the way to one starts or ends at."""
    nodes: set[str] = set()
    for citation in citations:
        nodes.add(citation.id)
        for hop in citation.path:
            nodes |= {hop.source, hop.target}
    return nodes


def contradiction_surfaced(
    answer: str,
    cited: Iterable[str],
    pairs: Iterable[tuple[str, str]],
    flags_contradiction: Callable[[str], bool],
) -> float | None:
    """Of the labeled contradicting pairs, the share the answer surfaces: both sides cited and
    the judge says the answer flags the disagreement. None when no pair is labeled."""
    pairs, cited = list(pairs), set(cited)
    if not pairs:
        return None
    both = [pair for pair in pairs if cited.issuperset(pair)]
    flagged = bool(both) and flags_contradiction(answer)
    return len(both) / len(pairs) if flagged else 0.0


class UsageMeter:
    """Wraps a provider and totals the tokens of the calls made through it."""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.name, self.model = provider.name, provider.model
        self.embedding_model = provider.embedding_model
        self.total_input = self.total_output = 0  # never reset: the whole run, judges included
        self.reset()

    def reset(self) -> None:
        self.input_tokens = self.output_tokens = self.calls = 0

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion:
        completion = self.provider.complete(prompt, params)
        self.input_tokens += completion.tokens_in
        self.output_tokens += completion.tokens_out + completion.tokens_thinking
        self.total_input += completion.tokens_in
        self.total_output += completion.tokens_out + completion.tokens_thinking
        self.calls += 1
        return completion

    def embed(self, texts: list[str], params: CompletionParams | None = None) -> Embedding:
        embedding = self.provider.embed(texts, params)
        self.input_tokens += embedding.tokens_in
        self.total_input += embedding.tokens_in
        self.calls += 1
        return embedding

    @property
    def usage(self) -> tuple[int, int]:
        return self.input_tokens, self.output_tokens


def abstention(
    answer: str, expected: bool, states_insufficient: Callable[[str], bool]
) -> float | None:
    """For a question the graph cannot answer: 1.0 when the answer is empty (no assunto, no
    sources) or the judge says it admits its sources fall short, else 0.0. None when the question
    is answerable."""
    if not expected:
        return None
    return 1.0 if not answer.strip() or states_insufficient(answer) else 0.0


class Outcome(dict):
    """What one question yields: a dict assayer routes by field, with the `usage_metadata` it
    reads token counts from."""

    usage_metadata: dict


def outcome_of(answer: CitedAnswer, usage: tuple[int, int]) -> Outcome:
    """One field per evaluator, so assayer's field router can hand each its own slice."""
    cited = [c.id for c in answer.citations]
    text = answer.answer or ""
    outcome = Outcome(
        answer=text,
        citations=cited,
        retrieved=list(answer.retrieved),
        sources={c.id: c.text for c in answer.citations},
        citation_check={"cited": cited, "retrieved": list(answer.retrieved)},
        path=sorted(path_nodes(answer.citations)),
        contradiction_check={"answer": text, "cited": cited},
        abstention_check={"answer": text},
        mentions_check=list(answer.unsupported),
    )
    outcome.usage_metadata = {"input_tokens": usage[0], "output_tokens": usage[1]}
    return outcome


def llm_flags_contradiction(provider: Provider) -> Callable[[str], bool]:
    """A judge that asks the model whether an answer points out that its sources disagree."""
    schema = {
        "title": "flags_contradiction",
        "type": "object",
        "properties": {"flags": {"type": "boolean"}},
        "required": ["flags"],
        "additionalProperties": False,
    }

    def judge(answer: str) -> bool:
        prompt = (
            "A resposta abaixo cita fontes jurídicas que divergem entre si. Ela aponta essa "
            "divergência ao leitor, em vez de apresentar só um dos lados? Responda em `flags`.\n\n"
            f"Resposta: {answer}"
        )
        reply = provider.complete(
            prompt, CompletionParams(pipeline_step="eval-contradiction", response_schema=schema)
        )
        return bool(json.loads(reply.text)["flags"])

    return judge


def llm_states_insufficiency(provider: Provider) -> Callable[[str], bool]:
    """A judge that asks the model whether an answer admits its sources fall short."""
    schema = {
        "title": "states_insufficiency",
        "type": "object",
        "properties": {"insufficient": {"type": "boolean"}},
        "required": ["insufficient"],
        "additionalProperties": False,
    }

    def judge(answer: str) -> bool:
        prompt = (
            "A resposta abaixo foi dada a partir de fontes jurídicas que não respondem à "
            "pergunta. Ela admite que as fontes não bastam (ou que não há resposta nelas), em "
            "vez de responder como se bastassem? Responda em `insufficient`.\n\n"
            f"Resposta: {answer}"
        )
        reply = provider.complete(
            prompt, CompletionParams(pipeline_step="eval-abstention", response_schema=schema)
        )
        return bool(json.loads(reply.text)["insufficient"])

    return judge
