"""SQLite adapter for the MetadataStore port: the enrichment records of ADR-0002."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from legal_radar.domain.model import EnrichmentRecord, EnrichmentStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichment_record (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'pending')),
    dropped INTEGER NOT NULL,
    skipped TEXT,
    resolved TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
)
"""
UPSERT = """
INSERT INTO enrichment_record
    (chunk_id, source_id, key, status, dropped, skipped, resolved, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (chunk_id) DO UPDATE SET source_id = excluded.source_id, key = excluded.key,
    status = excluded.status, dropped = excluded.dropped, skipped = excluded.skipped,
    resolved = excluded.resolved,
    updated_at = excluded.updated_at
"""


class SqliteMetadataStore:
    def __init__(self, path: Path | str = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute(SCHEMA)
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(enrichment_record)")}
        if "lei_id" in columns:  # a database from before decisions had records
            self._db.execute("ALTER TABLE enrichment_record RENAME COLUMN lei_id TO source_id")
            self._db.commit()

    def close(self) -> None:
        self._db.close()

    def record(self, record: EnrichmentRecord) -> None:
        with self._db:
            self._db.execute(
                UPSERT,
                (
                    record.chunk_id,
                    record.source_id,
                    record.key,
                    record.status.value,
                    record.dropped,
                    record.skipped,
                    json.dumps(record.resolved),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def records(self, source_id: str) -> dict[str, EnrichmentRecord]:
        rows = self._db.execute("SELECT * FROM enrichment_record WHERE source_id = ?", (source_id,))
        return {
            row["chunk_id"]: EnrichmentRecord(
                row["chunk_id"],
                row["source_id"],
                row["key"],
                EnrichmentStatus(row["status"]),
                row["dropped"],
                row["skipped"],
                tuple(json.loads(row["resolved"])),
            )
            for row in rows
        }

    def pending(self, source_id: str, current_keys: dict[str, str]) -> list[str]:
        stored = self.records(source_id)
        return [
            chunk_id
            for chunk_id, key in current_keys.items()
            if (r := stored.get(chunk_id)) is None
            or r.status is EnrichmentStatus.PENDING
            or r.key != key
        ]
