"""SQLite adapter for the VectorStore port: the vectors of a RAG baseline index (#79)."""

import array
import sqlite3
from pathlib import Path

from legal_radar.domain.model import StoredVector

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS vectors (chunk_id TEXT PRIMARY KEY, text_hash TEXT NOT NULL,"
    " model TEXT NOT NULL, vector BLOB NOT NULL)"
)


class SqliteVectorStore:
    def __init__(self, path: Path | str = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def load(self) -> dict[str, StoredVector]:
        rows = self._db.execute("SELECT chunk_id, text_hash, model, vector FROM vectors")
        return {
            chunk_id: StoredVector(text_hash, model, array.array("f", blob).tolist())
            for chunk_id, text_hash, model, blob in rows
        }

    def save(self, vectors: dict[str, StoredVector]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                [
                    (chunk_id, v.text_hash, v.model, array.array("f", v.vector).tobytes())
                    for chunk_id, v in vectors.items()
                ],
            )
