"""Enrichment evaluation harness (ADR-0002): per-edge scoring against a gold set, indirect metrics
and quality gates.

The unit scored is an edge `(type, source, target)`, not a span, so assayer's `NEREvaluator` does
not apply. Scoring is split by origin (`rule` / `llm`) and by relation type, so one can tell whether
the LLM adds value over the rules. Unresolved citations (no target) are not edges: they are
measured by the target-resolved rate instead. The gold set (`Gold set de enriquecimento`) lists, per
dispositivo, the edges it should yield; `edges: []` is a confirmed negative, a missing `edges` key
is an error because an unannotated dispositivo is not a negative.
"""

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from legal_radar.concepts import Vocabulary
from legal_radar.domain import Dispositivo, Relation, RelationType
from legal_radar.enricher import CONCEPT_RELATIONS, candidate_targets, enrich
from legal_radar.ports import Provider
from legal_radar.prompts import PromptLock
from legal_radar.relations import extract_relations

ALL = "all"
CONCEPT = "CONCEPT"  # aggregate of the dispositivo→conceito relation types
RULE_TYPES = (RelationType.REFERENCES, RelationType.REVOKES)  # `REVOKES` is never the LLM's
LLM_TYPES = (RelationType.REFERENCES, *CONCEPT_RELATIONS)
GATED_GROUPS = (("rule", ALL), ("llm", ALL), ("llm", CONCEPT), (ALL, ALL))


class GoldError(ValueError):
    pass


@dataclass(frozen=True)
class GoldEdge:
    type: RelationType
    source_id: str
    target_id: str


Gold = dict[str, frozenset[GoldEdge]]


def load_gold(text: str, vocabulary: Vocabulary | None = None) -> Gold:
    """Parse the gold set YAML: `dispositivos: [{id, edges: [{type, source?, target?}]}]`.

    The dispositivo is the default source of an edge, and the default target of a `REVOKES`. With a
    `vocabulary`, the file must pin its `vocabulary_hash`: concept edges only mean something
    against the vocabulary they were annotated with.
    """
    try:
        document = yaml.safe_load(text) or {}
        entries = document.get("dispositivos")
    except (yaml.YAMLError, AttributeError) as error:
        raise GoldError(f"unreadable gold set: {error}") from error
    if vocabulary is not None and document.get("vocabulary_hash") != vocabulary.hash:
        raise GoldError(
            f"the gold set was annotated against another vocabulary "
            f"(file {document.get('vocabulary_hash')!r}, current {vocabulary.hash!r})"
        )
    if not isinstance(entries, list):
        raise GoldError("the gold set needs a `dispositivos` list")
    gold: Gold = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise GoldError(f"gold entry without an `id`: {entry!r}")
        id_ = entry["id"]
        if id_ in gold:
            raise GoldError(f"duplicate gold entry: {id_}")
        if not isinstance(entry.get("edges"), list):
            raise GoldError(f"{id_}: `edges` is required (use [] for a confirmed negative)")
        gold[id_] = frozenset(_gold_edge(id_, e) for e in entry["edges"])
    return gold


def _gold_edge(id_: str, raw) -> GoldEdge:
    try:
        type_ = RelationType(raw["type"])
    except (KeyError, TypeError, ValueError) as error:
        raise GoldError(f"{id_}: edge without a valid `type`: {raw!r}") from error
    revokes = type_ is RelationType.REVOKES
    source = raw.get("source", None if revokes else id_)
    target = raw.get("target", id_ if revokes else None)
    if not isinstance(source, str) or not isinstance(target, str):
        raise GoldError(f"{id_}: edge needs a `source` and a `target`: {raw!r}")
    return GoldEdge(type_, source, target)


@dataclass(frozen=True)
class Outcome:
    """What enrichment produced for one dispositivo: the final edges (rules, then LLM)."""

    dispositivo: Dispositivo
    relations: list[Relation]
    dropped: int = 0  # items discarded for failing validation, by the rules or the LLM
    skipped: str | None = None
    failed: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


def enrich_dispositivos(
    dispositivos: Sequence[Dispositivo],
    vocabulary: Vocabulary,
    provider: Provider,
    lock: PromptLock | None = None,
    *,
    resolver=None,
    max_input_tokens: int | None = None,
    only: Collection[str] | None = None,
    on_progress: Callable[[int, int, Outcome], None] | None = None,
) -> list[Outcome]:
    """Run the rules and then the LLM over each dispositivo, as ingestion will (#29).

    A citation the LLM grounds replaces the unresolved LOW edge the rules left for it. With `only`,
    just those ids are enriched (the others still serve as ancestors and reference candidates, so
    no LLM call is spent on them); `on_progress(done, total, outcome)` fires after each one.
    """
    by_id = {d.id: d for d in dispositivos}
    ingested: dict[str, set[str]] = {}
    for d in dispositivos:
        ingested.setdefault(d.lei_id, set()).add(d.id)
    candidates = {
        lei: candidate_targets([d for d in dispositivos if d.lei_id == lei]) for lei in ingested
    }
    limits = {} if max_input_tokens is None else {"max_input_tokens": max_input_tokens}
    outcomes = []
    wanted = [d for d in dispositivos if only is None or d.id in only]
    for d in wanted:
        extraction = extract_relations(d, resolver, ingested)
        ancestors, parent = [], by_id.get(d.parent_id or "")
        while parent:
            ancestors.insert(0, parent)
            parent = by_id.get(parent.parent_id or "")
        result = enrich(
            d,
            vocabulary,
            provider,
            lock,
            ancestors=ancestors,
            unresolved=[r for r in extraction.relations if r.unresolved],
            candidates=candidates[d.lei_id],
            **limits,
        )
        kept = [r for r in extraction.relations if r not in result.resolved]
        outcome = Outcome(
            d,
            [*kept, *result.relations],
            extraction.dropped + result.dropped,
            result.skipped,
            result.failed,
            result.tokens_in,
            result.tokens_out,
        )
        outcomes.append(outcome)
        if on_progress:
            on_progress(len(outcomes), len(wanted), outcome)
    return outcomes


@dataclass(frozen=True)
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        return 2 * p * r / (p + r) if p + r else 0.0


def score_edges(outcomes: Sequence[Outcome], gold: Mapping[str, Collection[GoldEdge]]) -> dict:
    """Per-edge score keyed `(origin, type)`: origin is `rule`, `llm` or `all`; type is a
    `RelationType`, `CONCEPT` (the concept relations together) or `all`.

    Only dispositivos in the gold set are scored. For an origin, recall counts the gold edges of
    the types it can produce, so `llm` REFERENCES recall is "how many gold references the LLM
    found".
    """
    expected = {(g.type, g.source_id, g.target_id) for edges in gold.values() for g in edges}
    predicted: dict[str, set] = {"rule": set(), "llm": set()}
    for o in outcomes:
        if o.dispositivo.id not in gold:
            continue
        for r in o.relations:
            if r.unresolved or r.source_id is None or r.target_id is None:
                continue
            predicted[r.origin.value].add((r.type, r.source_id, r.target_id))
    predicted[ALL] = predicted["rule"] | predicted["llm"]
    allowed = {"rule": RULE_TYPES, "llm": LLM_TYPES, ALL: tuple(RelationType)}

    scores = {}
    for origin, edges in predicted.items():
        groups = {t: (t,) for t in allowed[origin]}
        groups[ALL] = allowed[origin]
        if origin != "rule":
            groups[CONCEPT] = CONCEPT_RELATIONS
        for key, types in groups.items():
            got = {e for e in edges if e[0] in types}
            want = {e for e in expected if e[0] in types}
            score = Score(len(got & want), len(got - want), len(want - got))
            if (origin, key) in GATED_GROUPS or score != Score():
                scores[(origin, key)] = score
    return scores


@dataclass(frozen=True)
class Indirect:
    """Continuous metrics that need no gold set; `None` when there is nothing to measure."""

    target_resolved_rate: float | None  # REFERENCES edges that have a target
    valid_evidence_rate: float | None  # edges whose evidence is a literal slice of the text
    drop_rate: float | None  # items discarded, of all items proposed


def indirect_metrics(outcomes: Sequence[Outcome]) -> Indirect:
    references = [r for o in outcomes for r in o.relations if r.type is RelationType.REFERENCES]
    edges = [(o.dispositivo, r) for o in outcomes for r in o.relations]
    valid = sum(any(r.evidence in source for source in (d.text, *d.revocations)) for d, r in edges)
    dropped = sum(o.dropped for o in outcomes)
    return Indirect(
        sum(r.target_id is not None for r in references) / len(references) if references else None,
        valid / len(edges) if edges else None,
        dropped / (len(edges) + dropped) if edges or dropped else None,
    )


@dataclass(frozen=True)
class Thresholds:
    """Gate limits. A precision or recall minimum of 0 disables that check."""

    min_precision_rules: float = 0.9
    min_recall_rules: float = 0.8
    min_precision_llm: float = 0.7
    min_recall_llm: float = 0.5  # of the concept edges: references are the rules' job
    min_target_resolved: float = 0.7
    min_valid_evidence: float = 0.99
    max_drop_rate: float = 0.2


def load_thresholds(path: Path | str) -> Thresholds:
    """Read `evaluation.yml`: `rules`/`llm` hold `min_precision` and `min_recall`; the indirect
    limits sit at the top level."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    values = {k: v for k, v in raw.items() if k not in ("rules", "llm")}
    for gate in ("rules", "llm"):
        for metric, value in (raw.get(gate) or {}).items():
            values[f"{metric}_{gate}"] = value
    try:
        return replace(Thresholds(), **values)
    except TypeError as error:
        raise ValueError(f"unknown threshold in {path}: {error}") from error


@dataclass(frozen=True)
class GateFailure:
    gate: str  # rules, llm, target_resolved, valid_evidence or drop_rate
    reason: str


def check_gates(scores: Mapping, indirect: Indirect, t: Thresholds) -> list[GateFailure]:
    """The quality gate of the deterministic rules, the one of the LLM, and the indirect ones.

    A recall with no gold edge to measure fails the gate: it cannot be certified. A precision with
    no prediction passes, because the recall check already catches a silent extractor.
    """
    failures: list[GateFailure] = []

    def at_least(gate, name, value, minimum):
        if minimum and (value is None or value < minimum):
            shown = "not measurable" if value is None else f"{value:.2f}"
            failures.append(GateFailure(gate, f"{name} {shown} < {minimum:.2f}"))

    def score(group):
        return scores.get(group, Score())

    if (precision := score(("rule", ALL)).precision) is not None:
        at_least("rules", "precision", precision, t.min_precision_rules)
    at_least("rules", "recall", score(("rule", ALL)).recall, t.min_recall_rules)
    if (precision := score(("llm", ALL)).precision) is not None:
        at_least("llm", "precision", precision, t.min_precision_llm)
    at_least("llm", "recall", score(("llm", CONCEPT)).recall, t.min_recall_llm)
    if indirect.target_resolved_rate is not None:
        at_least("target_resolved", "rate", indirect.target_resolved_rate, t.min_target_resolved)
    if indirect.valid_evidence_rate is not None:
        at_least("valid_evidence", "rate", indirect.valid_evidence_rate, t.min_valid_evidence)
    if indirect.drop_rate is not None and indirect.drop_rate > t.max_drop_rate:
        failures.append(
            GateFailure("drop_rate", f"rate {indirect.drop_rate:.2f} > {t.max_drop_rate:.2f}")
        )
    return failures


def persist_run(
    directory: Path | str, outcomes: Sequence[Outcome], run: dict, run_id: str | None = None
) -> Path:
    """Write one JSONL file: a header line, then each dispositivo's input and output, for audit."""
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path(directory) / f"enrichment-{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"run": {"id": run_id, **run}}]
    for o in outcomes:
        d = o.dispositivo
        lines.append(
            {
                "input": {
                    "id": d.id,
                    "lei_id": d.lei_id,
                    "path": d.path,
                    "kind": d.kind,
                    "text": d.text,
                },
                "output": {
                    "relations": [asdict(r) for r in o.relations],
                    "dropped": o.dropped,
                    "skipped": o.skipped,
                    "failed": o.failed,
                    "tokens_in": o.tokens_in,
                    "tokens_out": o.tokens_out,
                },
            }
        )
    path.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8"
    )
    return path
