"""Resolução de assunto: maps a raw query to a known assunto by embedding similarity, in memory."""

import math
from dataclasses import dataclass

from legal_radar.application.ports import Provider
from legal_radar.domain.anchors import ANCHORS, AnchorLei
from legal_radar.domain.llm import CompletionParams

DEFAULT_THRESHOLD = 0.5
PIPELINE_STEP = "assunto_resolution"


@dataclass(frozen=True)
class Resolution:
    assunto: str
    anchors: list[AnchorLei]
    score: float


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


class AssuntoResolver:
    """Embeds the anchor-assunto catalog once and matches queries by cosine similarity.

    The provider may fall back to another embedding model between calls; vectors from different
    models are not comparable, so the catalog is re-embedded whenever the query's model differs.
    """

    def __init__(
        self,
        provider: Provider,
        catalog: dict[str, list[AnchorLei]] | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self.provider = provider
        self.catalog = ANCHORS if catalog is None else catalog
        self.threshold = threshold
        self._names = list(self.catalog)
        self._model = ""
        self._vectors: list[list[float]] = []

    def resolve(self, query: str) -> Resolution | None:
        """The best-matching assunto, or None when nothing reaches the threshold."""
        if not self._names or not any(c.isalpha() for c in query):
            return None  # nothing to embed: `??` would still land near some assunto
        params = CompletionParams(pipeline_step=PIPELINE_STEP)
        query_embedding = self.provider.embed([query], params)
        if query_embedding.model != self._model:
            catalog = self.provider.embed(self._names, params)
            if catalog.model != query_embedding.model:  # fell back again: spaces differ
                return None
            self._vectors, self._model = catalog.vectors, catalog.model
        (vector,) = query_embedding.vectors
        score, name = max(
            (cosine(vector, candidate), name)
            for candidate, name in zip(self._vectors, self._names, strict=True)
        )
        if score < self.threshold:
            return None
        return Resolution(name, self.catalog[name], score)
