"""Ports the pipeline depends on; adapters live in `legal_radar.adapters`."""

from typing import Protocol

from legal_radar.domain import GraphBatch
from legal_radar.llm import Completion, CompletionParams


class Provider(Protocol):
    """A stateless model endpoint. Adapters raise `QuotaExhaustedError`, `RateLimitedError` or
    `TransientError`; the `Router` owns fallback, waiting, retry and logging."""

    name: str
    model: str

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion: ...


class GraphStore(Protocol):
    def write(self, batch: GraphBatch) -> None:
        """Idempotently upsert the batch's nodes and edges."""
