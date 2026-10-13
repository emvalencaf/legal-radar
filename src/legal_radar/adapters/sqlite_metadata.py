"""SQLite adapter for the MetadataStore port: the enrichment records of ADR-0002."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from legal_radar.domain import EnrichmentRecord, EnrichmentStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichment_record (
    chunk_id TEXT PRIMARY KEY,
    lei_id TEXT NOT NULL,
    key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'pending')),
    dropped INTEGER NOT NULL,
    skipped TEXT,
    updated_at TEXT NOT NULL
)
"""
UPSERT = """
INSERT INTO enrichment_record (chunk_id, lei_id, key, status, dropped, skipped, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (chunk_id) DO UPDATE SET lei_id = excluded.lei_id, key = excluded.key,
    status = excluded.status, dropped = excluded.dropped, skipped = excluded.skipped,
    updated_at = excluded.updated_at
"""


class SqliteMetadataStore:
    def __init__(self, path: Path | str = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def record(self, record: EnrichmentRecord) -> None:
        with self._db:
            self._db.execute(
                UPSERT,
                (
                    record.chunk_id,
                    record.lei_id,
                    record.key,
                    record.status.value,
                    record.dropped,
                    record.skipped,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def records(self, lei_id: str) -> dict[str, EnrichmentRecord]:
        rows = self._db.execute(
            "SELECT chunk_id, lei_id, key, status, dropped, skipped "
            "FROM enrichment_record WHERE lei_id = ?",
            (lei_id,),
        )
        return {
            row[0]: EnrichmentRecord(
                row[0], row[1], row[2], EnrichmentStatus(row[3]), row[4], row[5]
            )
            for row in rows
        }

    def pending(self, lei_id: str, current_keys: dict[str, str]) -> list[str]:
        stored = self.records(lei_id)
        return [
            chunk_id
            for chunk_id, key in current_keys.items()
            if (r := stored.get(chunk_id)) is None
            or r.status is EnrichmentStatus.PENDING
            or r.key != key
        ]
