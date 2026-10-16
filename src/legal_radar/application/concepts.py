"""Vocabulário de conceitos: one flat, curated YAML vocabulary per assunto (ADR-0003).

`load_vocabulary` validates a file and exposes `Vocabulary.hash`, the vocabulary part of the
enrichment idempotency key. `draft_candidates` has an LLM propose candidates for a human to curate.
"""

import copy
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import yaml

from legal_radar.adapters.prompt_lock import default_lock
from legal_radar.application.ports import Provider
from legal_radar.domain.llm import CompletionParams, content_hash
from legal_radar.domain.prompts import PromptLock
from legal_radar.settings import Settings

CATEGORIES = ("DIREITO", "ATOR", "PROCESSO", "REQUISITO", "PRINCIPIO", "TEORIA", "EFEITO")
ORIGINS = ("llm", "human")
STATUSES = ("draft", "curated")
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
VOCABULARY_PATHS = {
    "desconsideração da personalidade jurídica": Settings().concepts_dir
    / "desconsideracao_personalidade.yml",
}
# Dispositivo roots the drafter reads (with their parágrafos, incisos and alíneas); every
# jurisprudência in the graph is read too. CPC arts. 133-137 (ADR-0003) join once the CPC is
# ingested.
CORPUS_ROOTS = (
    "urn:lex:br:federal:lei:2002-01-10;10406#art50",  # CC art. 50
    "urn:lex:br:federal:lei:1990-09-11;8078#art28",  # CDC art. 28
)
logger = logging.getLogger(__name__)
COUNT_STEP = "concept_vocabulary_count"
PIPELINE_STEP = "concept_vocabulary_draft"


class VocabularyError(ValueError):
    """The vocabulary file breaks the format of ADR-0003."""


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    aliases: tuple[str, ...]
    instructions: str
    category: str
    # Provenance only: kept out of `Vocabulary.hash` so reviewing never reprocesses chunks.
    origin: str | None = None
    model: str | None = None  # `provider/model` that drafted it; required when origin is llm
    reviewed_by: str | None = None
    reviewed_on: str | None = None  # ISO date
    created_at: str | None = None  # ISO dates, maintained by hand or by `draft-concepts`
    updated_at: str | None = None
    sources: tuple[str, ...] = ()  # lineage: ids of the Dispositivo/Jurisprudencia it came from

    @property
    def reviewed(self) -> bool:
        return self.reviewed_by is not None


@dataclass(frozen=True)
class Vocabulary:
    assunto: str
    conceitos: tuple[Concept, ...]
    status: str = "draft"

    @property
    def hash(self) -> str:
        """Depends on the concepts' content only, not on file order or formatting."""
        entries = sorted(
            (_content(c) for c in self.conceitos),
            key=lambda entry: entry["id"],
        )
        return content_hash({"assunto": self.assunto, "conceitos": entries})


def _content(concept: Concept) -> dict:
    """The fields that define what a concept means; provenance is left out."""
    content = asdict(concept)
    for key in (
        "origin",
        "model",
        "reviewed_by",
        "reviewed_on",
        "created_at",
        "updated_at",
        "sources",
    ):
        del content[key]
    return {**content, "aliases": sorted(concept.aliases)}


def load_vocabulary(path: Path | str) -> Vocabulary:
    return parse_vocabulary(Path(path).read_text(encoding="utf-8"))


def load_registered(assunto: str) -> Vocabulary:
    """The committed vocabulary of a registered assunto; its file must declare that assunto."""
    if assunto not in VOCABULARY_PATHS:
        raise VocabularyError(f"no vocabulary registered for assunto {assunto!r}")
    vocabulary = load_vocabulary(VOCABULARY_PATHS[assunto])
    if vocabulary.assunto != assunto:
        raise VocabularyError(
            f"{VOCABULARY_PATHS[assunto].name} declares assunto {vocabulary.assunto!r}, "
            f"registered as {assunto!r}"
        )
    if vocabulary.status == "draft":
        unreviewed = sum(not c.reviewed for c in vocabulary.conceitos)
        logger.warning(
            "vocabulary %r is a draft: %d of %d concepts not reviewed",
            assunto,
            unreviewed,
            len(vocabulary.conceitos),
        )
    return vocabulary


def parse_vocabulary(text: str) -> Vocabulary:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise VocabularyError(f"invalid YAML: {error}") from error
    if not isinstance(document, dict):
        raise VocabularyError("expected a mapping with `assunto` and `conceitos`")
    assunto = document.get("assunto")
    if not isinstance(assunto, str) or not assunto.strip():
        raise VocabularyError("`assunto` must be a non-empty string")
    entries = document.get("conceitos")
    if not isinstance(entries, list) or not entries:
        raise VocabularyError("`conceitos` must be a non-empty list")

    concepts = tuple(_concept(entry) for entry in entries)
    _check_unique(concepts)
    status = document.get("status", "draft")
    if status not in STATUSES:
        raise VocabularyError(f"`status` must be one of {STATUSES}")
    if status == "curated" and not all(c.reviewed for c in concepts):
        raise VocabularyError("a curated vocabulary needs every concept reviewed")
    return Vocabulary(assunto, concepts, status)


def _concept(entry) -> Concept:
    if not isinstance(entry, dict):
        raise VocabularyError(f"concept entry must be a mapping, got {entry!r}")
    id_ = entry.get("id")
    if not isinstance(id_, str) or not ID_PATTERN.fullmatch(id_):
        raise VocabularyError(f"id {id_!r} must be lowercase ASCII snake_case")
    for key in ("label", "instructions"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise VocabularyError(f"{id_}: `{key}` must be a non-empty string")
    aliases = entry.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        raise VocabularyError(f"{id_}: `aliases` must be a list of non-empty strings")
    if entry.get("category") not in CATEGORIES:
        raise VocabularyError(f"{id_}: category must be one of {CATEGORIES}")
    origin = entry.get("origin")
    if origin is not None and origin not in ORIGINS:
        raise VocabularyError(f"{id_}: origin must be one of {ORIGINS}")
    model = entry.get("model")
    if origin == "llm" and (not isinstance(model, str) or not model.strip()):
        raise VocabularyError(f"{id_}: an llm-origin concept needs the `model` that drafted it")
    if origin != "llm" and model is not None:
        raise VocabularyError(f"{id_}: `model` only goes with origin llm")
    reviewed_by, reviewed_on = entry.get("reviewed_by"), entry.get("reviewed_on")
    if (reviewed_by is None) != (reviewed_on is None):
        raise VocabularyError(f"{id_}: `reviewed_by` and `reviewed_on` go together")
    if reviewed_by is not None:
        if not isinstance(reviewed_by, str) or not reviewed_by.strip():
            raise VocabularyError(f"{id_}: `reviewed_by` must be a non-empty string")
        reviewed_on = _iso_date(id_, "reviewed_on", reviewed_on)
    created_at = _iso_date(id_, "created_at", entry.get("created_at"))
    updated_at = _iso_date(id_, "updated_at", entry.get("updated_at"))
    if updated_at and not created_at:
        raise VocabularyError(f"{id_}: `updated_at` needs `created_at`")
    if updated_at and updated_at < created_at:
        raise VocabularyError(f"{id_}: `updated_at` is before `created_at`")
    sources = entry.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(x, str) and x.strip() for x in sources):
        raise VocabularyError(f"{id_}: `sources` must be a list of non-empty strings")
    return Concept(
        id_,
        entry["label"],
        tuple(aliases),
        entry["instructions"],
        entry["category"],
        origin,
        model,
        reviewed_by,
        reviewed_on,
        created_at,
        updated_at,
        tuple(sources),
    )


def _iso_date(id_: str, key: str, value) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise VocabularyError(f"{id_}: `{key}` must be an ISO date") from error


def _check_unique(concepts: tuple[Concept, ...]) -> None:
    ids: set[str] = set()
    terms: dict[str, str] = {}
    for concept in concepts:
        if concept.id in ids:
            raise VocabularyError(f"duplicate id {concept.id!r}")
        ids.add(concept.id)
        for term in (concept.label, *concept.aliases):
            owner = terms.setdefault(term.casefold(), concept.id)
            if owner != concept.id:
                raise VocabularyError(
                    f"term {term.casefold()!r} is used by {owner} and {concept.id}"
                )


def extract_schema(lock: PromptLock, source_ids: list[str]) -> dict:
    """The pinned step-2 schema; the Hub stores it static, so `sources` may only cite corpus ids
    by filling its enum here."""
    schema = copy.deepcopy(lock.schema("concepts-extract"))
    concept = schema["properties"]["conceitos"]["items"]
    concept["properties"]["sources"]["items"]["enum"] = sorted(source_ids)
    return schema


@dataclass(frozen=True)
class Draft:
    conceitos: list[dict]
    model: str  # `provider/model` that answered the extraction, after any fallback
    expected: int | None = None  # how many concepts the counting step found


def _answer(
    provider: Provider, prompt: str, step: str, schema: dict, key: str, snapshot: str | None
):
    completion = provider.complete(
        prompt,
        CompletionParams(pipeline_step=step, response_schema=schema, prompt_snapshot=snapshot),
    )
    try:
        return json.loads(completion.text)[key], completion
    except (ValueError, KeyError, TypeError) as error:
        raise VocabularyError(f"the LLM did not answer the {step} schema: {error}") from error


def draft_candidates(
    assunto: str, corpus: list[str], provider: Provider, lock: PromptLock | None = None
) -> Draft:
    """LLM-drafted candidates in two structured steps (count, then extract that many); a human
    curates them into the vocabulary."""
    lock = lock or default_lock()
    text = "\n\n---\n\n".join(corpus)
    quantidade, _ = _answer(
        provider,
        lock.render("concepts-count", assunto=assunto, corpus=text),
        COUNT_STEP,
        lock.schema("concepts-count"),
        "quantidade",
        lock.prompt_hash("concepts-count"),
    )
    if isinstance(quantidade, bool) or not isinstance(quantidade, int) or quantidade < 1:
        raise VocabularyError(f"the LLM counted {quantidade!r} concepts")
    conceitos, completion = _answer(
        provider,
        lock.render("concepts-extract", assunto=assunto, quantidade=quantidade, corpus=text),
        PIPELINE_STEP,
        extract_schema(lock, sorted(corpus_ids(corpus))),
        "conceitos",
        lock.prompt_hash("concepts-extract"),
    )
    if not isinstance(conceitos, list):
        raise VocabularyError("the LLM did not answer the extract schema: not a list")
    model = f"{completion.provider or provider.name}/{completion.model or provider.model}"
    return Draft(conceitos, model, quantidade)


def with_assunto(
    assunto: str, draft: Draft, corpus_ids: set[str] | None = None
) -> tuple[str, str | None]:
    """The draft as vocabulary YAML: a draft of its `assunto`, every concept marked as created now
    by the LLM that drafted it. Returns the text and any error from loading it; with `corpus_ids`,
    sources that are not in the corpus are reported too.
    """
    today = date.today().isoformat()
    conceitos = [
        {**entry, "origin": "llm", "model": draft.model, "created_at": today}
        for entry in draft.conceitos
    ]
    body = yaml.safe_dump(
        {"assunto": assunto, "status": "draft", "conceitos": conceitos},
        allow_unicode=True,
        sort_keys=False,
    )
    try:
        vocabulary = parse_vocabulary(body)
    except VocabularyError as error:
        return body, str(error)
    if draft.expected is not None and len(conceitos) != draft.expected:
        return body, f"the LLM counted {draft.expected} concepts but extracted {len(conceitos)}"
    if corpus_ids is not None:
        unknown = sorted({s for c in vocabulary.conceitos for s in c.sources} - corpus_ids)
        if unknown:
            return body, f"sources not in the corpus: {', '.join(unknown)}"
    return body, None


def corpus_ids(corpus: list[str]) -> set[str]:
    """The ids `graph_corpus` labels its entries with (`[id]` on the first line)."""
    return {entry.split("\n", 1)[0][1:-1] for entry in corpus}
