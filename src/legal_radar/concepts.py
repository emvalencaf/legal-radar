"""Vocabulário de conceitos: one flat, curated YAML vocabulary per assunto (ADR-0003).

`load_vocabulary` validates a file and exposes `Vocabulary.hash`, the vocabulary part of the
enrichment idempotency key. `draft_candidates` has an LLM propose candidates for a human to curate.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from neo4j import Driver

from legal_radar.llm import CompletionParams, content_hash
from legal_radar.ports import Provider

CATEGORIES = ("DIREITO", "ATOR", "PROCESSO", "REQUISITO", "PRINCIPIO", "TEORIA", "EFEITO")
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
VOCABULARY_PATHS = {
    "desconsideração da personalidade jurídica": Path(__file__).resolve().parents[2]
    / "concepts"
    / "desconsideracao_personalidade.yml",
}
# Dispositivo roots the drafter reads (with their parágrafos, incisos and alíneas); every
# jurisprudência in the graph is read too. CPC arts. 133-137 (ADR-0003) join once the CPC is
# ingested.
CORPUS_ROOTS = (
    "urn:lex:br:federal:lei:2002-01-10;10406#art50",  # CC art. 50
    "urn:lex:br:federal:lei:1990-09-11;8078#art28",  # CDC art. 28
)
CORPUS_QUERY = """
MATCH (d:Dispositivo)
WHERE any(root IN $roots WHERE d.id = root OR d.id STARTS WITH root + "_")
RETURN d.id AS id, d.text AS text
UNION
MATCH (j:Jurisprudencia)
RETURN j.id AS id, j.ementa + coalesce("\\n" + j.tese, "") AS text
"""
PIPELINE_STEP = "concept_vocabulary_draft"
FENCE = re.compile(r"^```\w*\n(.*?)\n?```\s*$", re.DOTALL)


class VocabularyError(ValueError):
    """The vocabulary file breaks the format of ADR-0003."""


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    aliases: tuple[str, ...]
    instructions: str
    category: str


@dataclass(frozen=True)
class Vocabulary:
    assunto: str
    conceitos: tuple[Concept, ...]

    @property
    def hash(self) -> str:
        """Depends on the concepts' content only, not on file order or formatting."""
        entries = sorted(
            ({**asdict(c), "aliases": sorted(c.aliases)} for c in self.conceitos),
            key=lambda entry: entry["id"],
        )
        return content_hash({"assunto": self.assunto, "conceitos": entries})


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
    return Vocabulary(assunto, concepts)


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
    return Concept(id_, entry["label"], tuple(aliases), entry["instructions"], entry["category"])


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


DRAFT_PROMPT = """\
Você ajuda a curar um vocabulário controlado de conceitos jurídicos brasileiros para o assunto
"{assunto}". Leia os textos abaixo (artigos de lei e ementas/teses de decisões) e proponha de 25 a
40 conceitos candidatos que aparecem neles de forma recorrente.

Responda somente com YAML, neste formato:

conceitos:
  - id: abuso_da_personalidade   # minúsculas, ASCII, snake_case
    label: Abuso da personalidade
    aliases: [desvio de finalidade]   # termos que o texto usa para o mesmo conceito
    instructions: Quando o texto trata de ... (uma frase, em português)
    category: REQUISITO   # exatamente uma de: {categories}

Cada conceito tem uma única categoria. Não proponha hierarquia entre conceitos.

Textos:
{corpus}
"""


def draft_candidates(assunto: str, corpus: list[str], provider: Provider) -> str:
    """LLM-drafted candidate YAML; a human curates it into the committed vocabulary."""
    prompt = DRAFT_PROMPT.format(
        assunto=assunto,
        categories=", ".join(CATEGORIES),
        corpus="\n\n---\n\n".join(corpus),
    )
    text = provider.complete(prompt, CompletionParams(pipeline_step=PIPELINE_STEP)).text.strip()
    fenced = FENCE.match(text)
    return (fenced.group(1) if fenced else text) + "\n"


def graph_corpus(driver: Driver) -> list[str]:
    """Texts of `CORPUS_ROOTS` and every jurisprudência (ementa + tese), in id order."""
    rows, _, _ = driver.execute_query(CORPUS_QUERY, roots=list(CORPUS_ROOTS))
    return [f"[{row['id']}]\n{row['text']}" for row in sorted(rows, key=lambda r: r["id"])]


def with_assunto(assunto: str, draft: str) -> tuple[str, str | None]:
    """Prefix the draft with its `assunto` and check it loads; returns the text and any error."""
    text = yaml.safe_dump({"assunto": assunto}, allow_unicode=True) + draft
    try:
        parse_vocabulary(text)
    except VocabularyError as error:
        return text, str(error)
    return text, None
