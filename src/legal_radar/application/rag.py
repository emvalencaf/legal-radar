"""Pure-RAG baselines to measure the graph's value (#79): embed every dispositivo and decision,
retrieve the top-k by cosine similarity, answer with the same `cited-answer` prompt and schema.

Two chunkings are compared with the graph run: `naive` (one chunk per dispositivo, its own text)
and `contextual` (the text preceded by the non-structural ancestors the enricher also builds
with `ancestors_of`). Neither uses an edge, a concept or a traversal."""

import array
import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from legal_radar.application.answer import (
    Citation,
    CitedAnswer,
    answer_from,
    jurisprudencia_text,
    strip_amendments,
    unsupported_mentions,
)
from legal_radar.application.assunto import cosine
from legal_radar.application.enricher import STRUCTURAL_KINDS, ancestors_of
from legal_radar.application.ports import Provider
from legal_radar.domain.llm import AllProvidersFailedError, CompletionParams
from legal_radar.domain.model import Dispositivo, Jurisprudencia
from legal_radar.domain.prompts import PromptLock
from legal_radar.settings import Settings

CHUNKINGS = ("naive", "contextual")
BASELINES = tuple(f"rag-{name}" for name in CHUNKINGS)
BATCH_SIZE = 50  # Gemini's batchEmbedContents takes at most 100 texts
INDEX_DIR = Settings().index_dir
EMBED_STEP = "rag_embedding"
RETRY_WAIT = 30.0  # seconds: free embedding tiers throttle per minute, counting every text
RETRIES = 8  # waits per batch before giving up; the saved batches make a rerun resume

log = logging.getLogger(__name__)


class RagError(RuntimeError):
    """The index cannot be built or queried: the embedding model changed under it."""


@dataclass(frozen=True)
class Chunk:
    id: str
    kind: str  # "Dispositivo" | "Jurisprudencia"
    text: str  # what is embedded and what the model is shown


def _live(d: Dispositivo) -> str:
    """The cleaned text of `d`, or "" when it is revoked, structural or says nothing."""
    return "" if d.revoked or d.kind in STRUCTURAL_KINDS else strip_amendments(d.text)


def build_chunks(
    dispositivos: list[Dispositivo], jurisprudencias: list[Jurisprudencia], contextual: bool
) -> list[Chunk]:
    """One chunk per live dispositivo and per decision, sorted by id. Revoked, empty and
    structural dispositivos (and a text that is only an amendment mark) are left out. A
    contextual chunk is the dispositivo's text after its live ancestors', farthest first."""
    by_id = {d.id: d for d in dispositivos}
    chunks = []
    for d in dispositivos:
        text = _live(d)
        if not text:
            continue
        if contextual:
            parents = (_live(a) for a in ancestors_of(d, by_id))
            text = "\n".join([*(p for p in parents if p), text])
        chunks.append(Chunk(d.id, "Dispositivo", text))
    chunks += [Chunk(j.id, "Jurisprudencia", jurisprudencia_text(j)) for j in jurisprudencias]
    return sorted(chunks, key=lambda c: c.id)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RagIndex:
    """Chunks with their vectors, all from one embedding model."""

    def __init__(self, chunks: list[Chunk], vectors: list[list[float]], model: str):
        self.chunks, self.vectors, self.model = chunks, vectors, model

    def top(self, vector: list[float], k: int) -> list[Chunk]:
        """The `k` chunks most similar to `vector`, best first (ties broken by id)."""
        ranked = sorted(
            zip(self.chunks, self.vectors, strict=True),
            key=lambda p: (-cosine(vector, p[1]), p[0].id),
        )
        return [chunk for chunk, _ in ranked[:k]]


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS vectors (chunk_id TEXT PRIMARY KEY, text_hash TEXT NOT NULL,"
        " model TEXT NOT NULL, vector BLOB NOT NULL)"
    )
    return db


def _embed_waiting(provider: Provider, texts: list[str], wait: float, retries: int):
    """`provider.embed`, waiting out a throttled provider up to `retries` times."""
    for attempt in range(retries + 1):
        try:
            return provider.embed(texts, CompletionParams(pipeline_step=EMBED_STEP))
        except AllProvidersFailedError:
            if attempt == retries:
                raise
            log.warning("embedding throttled; waiting %.0fs (%d/%d)", wait, attempt + 1, retries)
            time.sleep(wait)


def build_index(
    chunks: list[Chunk],
    provider: Provider,
    path: Path,
    batch_size: int = BATCH_SIZE,
    wait: float = RETRY_WAIT,
    retries: int = RETRIES,
) -> RagIndex:
    """The index of `chunks`, embedding only what `path` (SQLite) does not already hold: each
    batch is saved as it arrives, so a quota error mid-build resumes where it stopped. Raises
    `RagError` when the provider falls back to another embedding model, whose vectors cannot be
    mixed with the stored ones (delete `path` to rebuild with the new model). A throttled provider
    is waited out: `wait` seconds, up to `retries` times per batch."""
    db = _connect(path)
    try:
        stored = {
            row[0]: row[1:]
            for row in db.execute("SELECT chunk_id, text_hash, model, vector FROM vectors")
        }
        models = [row[1] for row in stored.values()]
        model = max(set(models), key=models.count) if models else None

        def fresh(chunk: Chunk) -> bool:
            row = stored.get(chunk.id)
            return bool(row) and row[0] == _digest(chunk.text) and row[1] == model

        pending = [c for c in chunks if not fresh(c)]
        vectors = {c.id: array.array("f", stored[c.id][2]).tolist() for c in chunks if fresh(c)}
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            embedding = _embed_waiting(provider, [c.text for c in batch], wait, retries)
            if model is None:
                model = embedding.model
            if embedding.model != model:
                raise RagError(
                    f"the embedding model changed from {model} to {embedding.model} while "
                    f"building {path.name}; {len(vectors)} of {len(chunks)} chunks are saved: "
                    "rerun when the first model is back, or delete the file to start over"
                )
            for chunk, vector in zip(batch, embedding.vectors, strict=True):
                vectors[chunk.id] = vector
                db.execute(
                    "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                    (chunk.id, _digest(chunk.text), model, array.array("f", vector).tobytes()),
                )
            db.commit()
    finally:
        db.close()
    if not chunks:
        raise RagError("there is nothing to index: the graph has no dispositivo or decision")
    return RagIndex(chunks, [vectors[c.id] for c in chunks], model or "")


def index_path(chunking: str, directory: Path = INDEX_DIR) -> Path:
    return directory / f"rag-{chunking}.sqlite"


class RagBaseline:
    """`ask(query) -> CitedAnswer` over a vector index instead of the graph."""

    def __init__(self, name: str, index: RagIndex, provider: Provider, k: int, lock: PromptLock):
        self.name, self.index, self.provider, self.k = name, index, provider, k
        self.lock = lock

    def ask(self, query: str) -> CitedAnswer:
        embedding = self.provider.embed([query], CompletionParams(pipeline_step=EMBED_STEP))
        if embedding.model != self.index.model:
            raise RagError(
                f"the query was embedded with {embedding.model}, the index with {self.index.model}"
            )
        top = self.index.top(embedding.vectors[0], self.k)
        texts = {c.id: c.text for c in top}
        answer, cited = answer_from(query, texts, self.provider, self.lock)
        by_id = {c.id: c for c in top}
        citations = [Citation(i, by_id[i].kind, [], by_id[i].text) for i in cited]
        unsupported = unsupported_mentions(answer or "", list(texts))
        return CitedAnswer(query, self.name, answer, citations, list(texts), unsupported)
