"""Domain entities written to the knowledge graph."""

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class Lei:
    id: str
    title: str
    planalto_url: str | None = None


@dataclass(frozen=True)
class Dispositivo:
    """A structural unit of a lei (títulos down to alíneas), keyed by `{lei_id}#{path}`."""

    id: str
    lei_id: str
    path: str
    text: str
    parent_id: str | None = None
    kind: str = "artigo"
    revoked: bool = False  # carries a `(Revogado …)` mark; the text is kept, no longer live law
    revocations: tuple[str, ...] = ()  # the literal marks, moved out of `text`


@dataclass(frozen=True)
class Jurisprudencia:
    """A court decision, keyed `{court}:{court-native id}`; ementa, tese and decisão only."""

    id: str
    court: str
    number: str
    ementa: str
    decisao: str
    tese: str | None = None


@dataclass(frozen=True)
class Conceito:
    id: str


@dataclass(frozen=True)
class ConceptLink:
    dispositivo_id: str
    conceito_id: str


@dataclass(frozen=True)
class GraphBatch:
    lei: Lei
    dispositivos: list[Dispositivo]
    conceitos: list[Conceito]
    links: list[ConceptLink]
    relations: list["Relation"] = field(default_factory=list)


@dataclass(frozen=True)
class Hop:
    """One edge walked from the anchor: `source -[type]-> target` (as stored in the graph)."""

    type: str
    source: str
    target: str
    confidence: str | None = None  # the edge's `Confidence` value; PARTS hops carry none


@dataclass(frozen=True)
class Context:
    """What a traversal retrieved: the nodes reached and, per node id, the hops that reached it;
    `revocations` are the leis revoking a reached dispositivo, kept apart as they reach no node."""

    dispositivos: list[Dispositivo]
    jurisprudencias: list[Jurisprudencia]
    paths: dict[str, list[Hop]]
    revocations: list[Hop] = field(default_factory=list)  # REVOKES edges into a retrieved node


class RelationType(StrEnum):
    REFERENCES = "REFERENCES"
    REVOKES = "REVOKES"
    # dispositivo → conceito, from the LLM enricher (ADR-0002)
    DEFINES = "DEFINES"
    APPLIES_TO = "APPLIES_TO"
    OBLIGES = "OBLIGES"
    PROHIBITS = "PROHIBITS"
    EXCEPTS = "EXCEPTS"
    RELATES_TO = "RELATES_TO"


class Confidence(StrEnum):
    """Reliability of a relation, derived from how it was extracted (ADR-0002)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Origin(StrEnum):
    RULE = "rule"
    LLM = "llm"


@dataclass(frozen=True)
class Relation:
    """An edge `source -[type]-> target` extracted from the text of one dispositivo.

    An endpoint that could not be resolved to an id is `None`, and `unresolved` keeps the
    citation as written so it is not lost. `evidence` is a literal substring of the chunk.
    """

    type: RelationType
    source_id: str | None
    target_id: str | None
    confidence: Confidence
    origin: Origin
    evidence: str
    unresolved: str | None = None


class EnrichmentStatus(StrEnum):
    OK = "ok"
    PENDING = "pending"


@dataclass(frozen=True)
class EnrichmentRecord:
    """The persisted state of a chunk that went through the LLM (CONTEXT.md: registro de
    enriquecimento). Kept outside the graph; `key` is the whole idempotency key."""

    chunk_id: str
    source_id: str  # the lei of a dispositivo, or the court of a decision: what groups records
    key: str
    status: EnrichmentStatus
    dropped: int = 0
    skipped: str | None = None  # why no call was made (`too_long`), or None
    resolved: tuple[str, ...] = ()  # the unresolved citations the LLM grounded


CONCEPT_RELATIONS = (
    RelationType.DEFINES,
    RelationType.APPLIES_TO,
    RelationType.OBLIGES,
    RelationType.PROHIBITS,
    RelationType.EXCEPTS,
    RelationType.RELATES_TO,
)
