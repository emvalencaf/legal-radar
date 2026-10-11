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
