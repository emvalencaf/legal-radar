"""Ports the pipeline depends on; adapters live in `legal_radar.adapters`."""

from typing import Protocol

from legal_radar.domain import (
    Context,
    EnrichmentRecord,
    GraphBatch,
    Jurisprudencia,
    Relation,
)
from legal_radar.llm import Completion, CompletionParams, Embedding


class Provider(Protocol):
    """A stateless model endpoint. Adapters raise `QuotaExhaustedError`, `RateLimitedError` or
    `TransientError`; the `Router` owns fallback, waiting, retry and logging."""

    name: str
    model: str
    embedding_model: str

    def complete(self, prompt: str, params: CompletionParams | None = None) -> Completion: ...

    def embed(self, texts: list[str], params: CompletionParams | None = None) -> Embedding:
        """One vector per text, all from `embedding_model`. Vectors from different models live in
        different spaces and must never be compared."""


class GraphStore(Protocol):
    def write(self, batch: GraphBatch) -> None:
        """Idempotently upsert the batch's nodes and edges.

        A relation whose lei the graph lacks becomes an edge to a stub Lei node keyed by its URN;
        one whose endpoint is unresolved is kept as an attribute of the node it starts from."""

    def write_jurisprudencia(self, items: list[Jurisprudencia]) -> None:
        """Idempotently upsert the jurisprudência nodes."""

    def replace_llm_relations(self, chunk_id: str, relations: list[Relation]) -> None:
        """Atomically swap the `llm`-origin edges starting at one dispositivo for `relations`.
        `rule`-origin edges are never touched."""

    def resolve_citations(self, chunk_id: str, citations: list[str]) -> None:
        """Forget the unresolved citations of one dispositivo that an `llm` edge now grounds.
        Idempotent: the rules keep writing them on every ingestion."""


class MetadataStore(Protocol):
    """Ingestion metadata kept apart from the graph (ADR-0002): one record per chunk the LLM saw."""

    def record(self, record: EnrichmentRecord) -> None:
        """Upsert the chunk's record, stamping the update time."""

    def records(self, source_id: str) -> dict[str, EnrichmentRecord]:
        """The records of one source (a lei or a court), by chunk id."""

    def pending(self, source_id: str, current_keys: dict[str, str]) -> list[str]:
        """The chunks of `current_keys` (chunk id -> current key) that are pending: no record, a
        `pending` record, or a stored key that differs. Keeps the order of `current_keys`."""


class GraphReader(Protocol):
    def lei_ids(self) -> list[str]:
        """The ids (URNs) of every lei in the graph, sorted."""

    def traverse(self, anchor_ids: list[str]) -> Context:
        """Walk `PARTS` down from the anchors (leis or dispositivos), then 1 hop of `REFERENCES`
        (a dispositivo's outgoing ones, a jurisprudência's citations of reached dispositivos),
        with no scoring or cap. Deterministic: same anchors, same context, sorted by id."""


class PageSource(Protocol):
    """Fetches a web page as text, following redirects. LexML sits behind a JS bot-wall, so its
    production adapter drives a real browser."""

    def get(self, url: str) -> str: ...


class JsonApi(Protocol):
    """Calls a court's JSON API from inside a page of its own site (same-origin, past its WAF)."""

    def post_json(self, url: str, body: dict) -> str: ...


class FormPages(Protocol):
    """Submits a page's search form and returns the result page; the session-bound STJ search
    cannot be reached by a plain GET."""

    def submit_form(self, url: str, form: str, fields: dict[str, str]) -> str: ...


class JurisprudenciaFetcher(Protocol):
    """One court's search, however it is reached; every court looks the same to the pipeline."""

    def search(self, query: str, limit: int) -> list[Jurisprudencia]: ...
