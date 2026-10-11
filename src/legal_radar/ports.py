"""Ports the pipeline depends on; adapters live in `legal_radar.adapters`."""

from typing import Protocol

from legal_radar.domain import GraphBatch


class Provider(Protocol):
    def complete(self, prompt: str) -> str: ...


class GraphStore(Protocol):
    def write(self, batch: GraphBatch) -> None:
        """Idempotently upsert the batch's nodes and edges."""
