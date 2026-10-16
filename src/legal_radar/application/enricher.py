"""LLM enricher: dispositivo → conceito edges and grounded references (ADR-0002, ADR-0007).

`enrich` is a pure function of one dispositivo: one call to the provider, no persistence and no
`pending` bookkeeping (issue #29). Every norm-bearing dispositivo is sent for concepts; only the
unresolved citations the rules left behind are sent for reference resolution, and the LLM can only
pick their target from a closed list of candidates. Confidence comes from provenance: every edge
returned is MEDIUM and origin `llm`. Items that fail validation are dropped and counted.
"""

import copy
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from legal_radar.application.concepts import Vocabulary
from legal_radar.application.enrichment import DECISION_PROMPT, ENRICHMENT_PROMPT
from legal_radar.application.ports import Provider
from legal_radar.domain.llm import CompletionParams, content_hash
from legal_radar.domain.model import (
    CONCEPT_RELATIONS,
    Confidence,
    Dispositivo,
    Jurisprudencia,
    Origin,
    Relation,
    RelationType,
)
from legal_radar.domain.prompts import PromptLock
from legal_radar.domain.relations import CURATED_CODES

logger = logging.getLogger(__name__)

MAX_INPUT_TOKENS = 8000  # per call; the default of the configurable ceiling
CHARS_PER_TOKEN = 4  # rough estimate; no tokenizer is shipped
STRUCTURAL_KINDS = ("parte", "livro", "titulo", "subtitulo", "capitulo", "secao", "subsecao")
DECISION_RELATIONS = CONCEPT_RELATIONS  # a thesis can require, forbid and carve out (ADR-0008)
RELATION_DEFINITIONS = {
    RelationType.DEFINES: "o dispositivo define o conceito",
    RelationType.APPLIES_TO: "o dispositivo se aplica ao conceito (ator, situação, instituto)",
    RelationType.OBLIGES: "o dispositivo impõe um dever relativo ao conceito",
    RelationType.PROHIBITS: "o dispositivo proíbe algo relativo ao conceito",
    RelationType.EXCEPTS: "o dispositivo excepciona ou afasta o conceito",
    RelationType.RELATES_TO: "relação que não se encaixa nas demais",
}
DECISION_DEFINITIONS = {
    RelationType.APPLIES_TO: "a corte aplica o conceito ao caso ou o toma por fundamento (padrão)",
    RelationType.DEFINES: "a corte fixa o sentido do conceito; citar a lei não é definir",
    RelationType.OBLIGES: "a posição da corte impõe dever, ônus ou requisito sobre o conceito",
    RelationType.PROHIBITS: "a posição da corte veda ou não admite algo relativo ao conceito",
    RelationType.EXCEPTS: "a posição da corte cria ressalva, limite ou afasta o conceito",
    RelationType.RELATES_TO: "só se nenhuma outra couber e o conceito for central na decisão",
}
# Source of the Hub prompt `dispositivo-enrichment`. Everything before `## Dispositivo` is the
# stable prefix shared by every call of an assunto, so providers can cache it.
ENRICHMENT_TEMPLATE = """Você relaciona dispositivos legais a conceitos do assunto "{assunto}".

## Relações possíveis
{relacoes}

## Vocabulário de conceitos
Use somente os ids abaixo. Se nenhum conceito se aplicar, devolva a lista vazia.
{vocabulario}

## Dispositivo
Lei: {lei}
Caminho: {caminho}

Texto dos dispositivos superiores (apenas contexto; não use como evidência):
{ancestrais}

Texto do dispositivo alvo:
{texto}

## Citações não resolvidas
{citacoes}

Alvos possíveis para as citações (escolha um da lista ou omita a citação):
{candidatos}

Responda em JSON. `evidence` é sempre um trecho literal do texto do dispositivo alvo.
Cada item de `conceitos` tem `conceito_id`, `relacao` e `evidence`.
Cada item de `referencias` tem `citacao`, `alvo` e `evidence`."""


# Source of the Hub prompt `jurisprudencia-enrichment`; the stable prefix ends at `## Decisão`.
DECISION_TEMPLATE = """Você relaciona uma decisão judicial a conceitos do assunto "{assunto}".
Seja conservador: uma lista vazia é a resposta esperada quando houver dúvida.

## Relações possíveis
{relacoes}

## Regras
- Só conta a posição da própria corte. Ignore o que a parte alega ("o recorrente sustenta")
  e o que a instância de origem decidiu ("o tribunal a quo entendeu").
- Citar um dispositivo, transcrever doutrina ou apenas mencionar um conceito não é relação.
- Uma negação muda a relação: se a corte afasta ou não admite o conceito, use EXCEPTS ou
  PROHIBITS, nunca APPLIES_TO.
- OBLIGES, PROHIBITS, EXCEPTS e DEFINES precisam de evidência da tese ou do que a corte
  decide; na dúvida, use APPLIES_TO ou omita.
- No máximo uma relação por conceito: a mais específica.
- `evidence` é uma oração completa e literal, nunca um título ou cabeçalho em letras maiúsculas.

## Vocabulário de conceitos
Use somente os ids abaixo. Se nenhum conceito se aplicar, devolva a lista vazia.
{vocabulario}

## Decisão
Tribunal: {tribunal}
Número: {numero}

Ementa:
{ementa}

Tese:
{tese}

Responda em JSON. `evidence` é sempre um trecho literal da ementa ou da tese.
Cada item de `conceitos` tem `conceito_id`, `relacao` e `evidence`."""


@dataclass(frozen=True)
class Enrichment:
    relations: list[Relation] = field(default_factory=list)  # concept edges + inferred references
    resolved: list[Relation] = field(default_factory=list)  # the unresolved citations now grounded
    dropped: int = 0  # items discarded for failing validation
    out_of_vocabulary: list[str] = field(default_factory=list)  # proposed ids, for curation
    skipped: str | None = None  # why no call was made: revoked, structural, empty or too_long
    failed: str | None = None  # the reply was not parseable; the dispositivo should stay pending
    tokens_in: int = 0
    tokens_out: int = 0


def enrich(
    d: Dispositivo,
    vocabulary: Vocabulary,
    provider: Provider,
    lock: PromptLock,
    *,
    ancestors: Sequence[Dispositivo] = (),
    unresolved: Sequence[Relation] = (),
    candidates: Sequence[str] = (),
    max_input_tokens: int = MAX_INPUT_TOKENS,
) -> Enrichment:
    """Concept edges of `d`, and a target for each of its `unresolved` citations when the LLM can
    ground one in `candidates`. `ancestors` run from the farthest to the nearest."""
    if reason := triage(d):
        return Enrichment(skipped=reason)
    citations = [u for u in unresolved if u.unresolved]
    candidates = sorted(set(candidates)) if citations else []
    kept = list(ancestors)
    while (prompt := _prompt(d, kept, vocabulary, citations, candidates, lock)) and _tokens(
        prompt
    ) > max_input_tokens:
        if not kept:
            return Enrichment(skipped="too_long")
        kept.pop(0)  # the farthest ancestor goes first
    schema = _schema(vocabulary, citations, candidates)
    completion = provider.complete(
        prompt,
        CompletionParams(
            pipeline_step="enrich",
            response_schema=schema,
            prompt_snapshot=content_hash(
                {"prompt": lock.prompt_hash(ENRICHMENT_PROMPT), "schema": schema}
            ),
        ),
    )
    usage = {"tokens_in": completion.tokens_in, "tokens_out": completion.tokens_out}
    try:
        reply = json.loads(completion.text)
        items = {key: reply[key] for key in ("conceitos", "referencias")}
        if not all(isinstance(v, list) for v in items.values()):
            raise TypeError("`conceitos` and `referencias` must be lists")
    except (ValueError, KeyError, TypeError) as error:
        logger.warning("enrichment reply of %s is unusable: %s", d.id, error)
        return Enrichment(failed=str(error), **usage)

    result = _Result(d.id, (d.text,), vocabulary, CONCEPT_RELATIONS, citations, set(candidates))
    for item in items["conceitos"]:
        result.concept(item)
    for item in items["referencias"]:
        result.reference(item)
    return Enrichment(
        result.relations, result.resolved, result.dropped, result.out_of_vocabulary, **usage
    )


def decision_texts(j: Jurisprudencia) -> tuple[str, ...]:
    """The parts of a decision the LLM reads and evidence may point at: ementa, then tese."""
    return tuple(t for t in (j.ementa, j.tese) if t and t.strip())


def enrich_decision(
    j: Jurisprudencia,
    vocabulary: Vocabulary,
    provider: Provider,
    lock: PromptLock,
    *,
    max_input_tokens: int = MAX_INPUT_TOKENS,
) -> Enrichment:
    """Concept edges of a decision, read from its ementa and tese only (never the decisão). Only
    `DECISION_RELATIONS` apply, and `evidence` is a literal slice of the ementa or of the tese."""
    if not j.ementa.strip():
        return Enrichment(skipped="empty")
    texts = decision_texts(j)
    prompt = lock.render(
        DECISION_PROMPT,
        assunto=vocabulary.assunto,
        relacoes="\n".join(f"- {t.value}: {text}" for t, text in DECISION_DEFINITIONS.items()),
        vocabulario=_vocabulary_block(vocabulary),
        tribunal=j.court,
        numero=j.number,
        ementa=j.ementa or "(sem ementa)",
        tese=j.tese or "(sem tese)",
    )
    if _tokens(prompt) > max_input_tokens:
        return Enrichment(skipped="too_long")
    schema = _decision_schema(vocabulary)
    completion = provider.complete(
        prompt,
        CompletionParams(
            pipeline_step="enrich",
            response_schema=schema,
            prompt_snapshot=content_hash(
                {"prompt": lock.prompt_hash(DECISION_PROMPT), "schema": schema}
            ),
        ),
    )
    usage = {"tokens_in": completion.tokens_in, "tokens_out": completion.tokens_out}
    try:
        items = json.loads(completion.text)["conceitos"]
        if not isinstance(items, list):
            raise TypeError("`conceitos` must be a list")
    except (ValueError, KeyError, TypeError) as error:
        logger.warning("enrichment reply of %s is unusable: %s", j.id, error)
        return Enrichment(failed=str(error), **usage)
    result = _Result(j.id, texts, vocabulary, DECISION_RELATIONS, [], set(), headings=False)
    for item in items:
        result.concept(item)
    return Enrichment(result.relations, [], result.dropped, result.out_of_vocabulary, **usage)


def ancestors_of(d: Dispositivo, by_id: dict[str, Dispositivo]) -> list[Dispositivo]:
    """The parents of `d` from the farthest to the nearest."""
    ancestors, parent = [], by_id.get(d.parent_id or "")
    while parent:
        ancestors.insert(0, parent)
        parent = by_id.get(parent.parent_id or "")
    return ancestors


def candidate_targets(lei_dispositivos: Sequence[Dispositivo]) -> list[str]:
    """The closed list of reference targets: dispositivos of the same lei and the curated codes."""
    return [*(d.id for d in lei_dispositivos), *CURATED_CODES]


def triage(d: Dispositivo) -> str | None:
    """Why `d` is never sent to the LLM (revoked, structural or empty), or None."""
    if d.revoked:
        return "revoked"
    if d.kind in STRUCTURAL_KINDS:
        return "structural"
    if not d.text.strip():
        return "empty"
    return None


def _tokens(prompt: str) -> int:
    return -(-len(prompt) // CHARS_PER_TOKEN)


def _vocabulary_block(vocabulary: Vocabulary) -> str:
    return "\n".join(
        f"- {c.id} ({c.category}): {c.label}"
        + (f"; também: {', '.join(c.aliases)}" if c.aliases else "")
        + f". {c.instructions}"
        for c in sorted(vocabulary.conceitos, key=lambda c: c.id)
    )


def _prompt(d, ancestors, vocabulary, citations, candidates, lock) -> str:
    concepts = _vocabulary_block(vocabulary)
    return lock.render(
        ENRICHMENT_PROMPT,
        assunto=vocabulary.assunto,
        relacoes="\n".join(f"- {t.value}: {text}" for t, text in RELATION_DEFINITIONS.items()),
        vocabulario=concepts,
        lei=d.lei_id,
        caminho=d.path,
        ancestrais="\n".join(f"[{a.path}] {a.text}" for a in ancestors) or "(nenhum)",
        texto=d.text,
        citacoes="\n".join(f"- {c.unresolved}" for c in citations) or "(nenhuma)",
        candidatos="\n".join(f"- {c}" for c in candidates) or "(nenhum)",
    )


def _schema(
    vocabulary: Vocabulary, citations: Sequence[Relation], candidates: Sequence[str]
) -> dict:
    schema = copy.deepcopy(ENRICHMENT_SCHEMA)
    concept = schema["properties"]["conceitos"]["items"]["properties"]
    concept["conceito_id"]["enum"] = sorted(c.id for c in vocabulary.conceitos)
    concept["relacao"]["enum"] = [t.value for t in CONCEPT_RELATIONS]
    references = schema["properties"]["referencias"]
    unresolved = sorted({c.unresolved for c in citations})
    if unresolved and candidates:
        reference = references["items"]["properties"]
        reference["citacao"]["enum"] = unresolved
        reference["alvo"]["enum"] = list(candidates)
    else:  # no citation to resolve: constrained decoding rejects an empty `enum`, so allow none
        references["maxItems"] = 0
    return schema


def _decision_schema(vocabulary: Vocabulary) -> dict:
    schema = copy.deepcopy(DECISION_SCHEMA)
    concept = schema["properties"]["conceitos"]["items"]["properties"]
    concept["conceito_id"]["enum"] = sorted(c.id for c in vocabulary.conceitos)
    concept["relacao"]["enum"] = [t.value for t in DECISION_RELATIONS]
    return schema


ENRICHMENT_SCHEMA = {
    "title": "dispositivo_enrichment",
    "type": "object",
    "properties": {
        "conceitos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "conceito_id": {"type": "string"},
                    "relacao": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["conceito_id", "relacao", "evidence"],
            },
        },
        "referencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "citacao": {"type": "string"},
                    "alvo": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["citacao", "alvo", "evidence"],
            },
        },
    },
    "required": ["conceitos", "referencias"],
}


DECISION_SCHEMA = {
    "title": "jurisprudencia_enrichment",
    "type": "object",
    "properties": {"conceitos": ENRICHMENT_SCHEMA["properties"]["conceitos"]},
    "required": ["conceitos"],
}


class _Result:
    """Validates the reply item by item, keeping what passes and counting what does not."""

    def __init__(
        self, source_id, texts, vocabulary, relations, citations, candidates, headings=True
    ):
        self.source_id = source_id
        self.texts = texts
        self.headings = headings  # whether evidence in capitals (a heading) is accepted
        self.allowed = {t.value for t in relations}
        self.ids = {c.id for c in vocabulary.conceitos}
        self.citations = {c.unresolved: c for c in citations}
        self.candidates = candidates
        self.relations: list[Relation] = []
        self.resolved: list[Relation] = []
        self.dropped = 0
        self.out_of_vocabulary: list[str] = []

    def concept(self, item) -> None:
        evidence = self._evidence(item, "conceito_id", "relacao")
        if evidence is None:
            return
        if item["conceito_id"] not in self.ids:
            self.out_of_vocabulary.append(str(item["conceito_id"]))
            return self._drop(item)
        if item["relacao"] not in self.allowed:
            return self._drop(item)
        self.relations.append(
            Relation(
                RelationType(item["relacao"]),
                self.source_id,
                item["conceito_id"],
                Confidence.MEDIUM,
                Origin.LLM,
                evidence,
            )
        )

    def reference(self, item) -> None:
        evidence = self._evidence(item, "citacao", "alvo")
        if evidence is None:
            return
        citation = self.citations.get(item["citacao"])
        if citation is None or item["alvo"] not in self.candidates or citation in self.resolved:
            return self._drop(item)
        self.resolved.append(citation)
        self.relations.append(
            Relation(
                RelationType.REFERENCES,
                self.source_id,
                item["alvo"],
                Confidence.MEDIUM,
                Origin.LLM,
                evidence,
                None,
            )
        )

    def _evidence(self, item, *keys) -> str | None:
        """The literal slice of the target's own text that `item["evidence"]` points at."""
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) for k in (*keys, "evidence")
        ):
            self._drop(item)
            return None
        words = item["evidence"].split()
        pattern = r"\s+".join(map(re.escape, words))
        match = (
            next(filter(None, (re.search(pattern, t) for t in self.texts)), None) if words else None
        )
        if match is None:
            self._drop(item)
            return None
        if not self.headings and match[0].isupper():
            self._drop(item)
            return None
        return match[0]

    def _drop(self, item) -> None:
        self.dropped += 1
        logger.warning("dropped an enrichment item of %s: %r", self.source_id, item)
