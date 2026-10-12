"""Domain entities written to the knowledge graph."""

from dataclasses import dataclass


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


@dataclass(frozen=True)
class Hop:
    """One edge walked from the anchor: `source -[type]-> target` (as stored in the graph)."""

    type: str
    source: str
    target: str


@dataclass(frozen=True)
class Context:
    """What a traversal retrieved: the nodes reached and, per node id, the hops that reached it."""

    dispositivos: list[Dispositivo]
    jurisprudencias: list[Jurisprudencia]
    paths: dict[str, list[Hop]]
