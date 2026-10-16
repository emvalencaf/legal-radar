from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore
from legal_radar.domain.model import EnrichmentRecord, EnrichmentStatus

STATUTE = "urn:lex:br:federal:lei:2002-01-10;10406"


def rec(chunk, key="k1", status=EnrichmentStatus.OK, statute=STATUTE, **kwargs):
    return EnrichmentRecord(chunk, statute, key, status, **kwargs)


def test_chunk_without_a_record_is_pending():
    assert SqliteMetadataStore().pending(STATUTE, {"a": "k1", "b": "k1"}) == ["a", "b"]


def test_ok_record_with_the_same_key_is_not_pending():
    store = SqliteMetadataStore()
    store.record(rec("a"))

    assert store.pending(STATUTE, {"a": "k1", "b": "k1"}) == ["b"]


def test_changed_key_or_pending_status_returns_the_chunk_to_pending():
    store = SqliteMetadataStore()
    store.record(rec("a"))
    store.record(rec("b", status=EnrichmentStatus.PENDING))
    store.record(rec("c"))

    assert store.pending(STATUTE, {"a": "k2", "b": "k1", "c": "k1"}) == ["a", "b"]


def test_record_is_upserted_and_scoped_to_its_statute(tmp_path):
    path = tmp_path / "nested" / "meta.sqlite"
    store = SqliteMetadataStore(path)
    store.record(rec("a", dropped=2, skipped="too_long", resolved=("lei 9",)))
    store.record(rec("a", key="k2", dropped=1))
    store.record(rec("z", statute="other"))
    store.close()

    assert SqliteMetadataStore(path).records(STATUTE) == {"a": rec("a", key="k2", dropped=1)}


def test_resolved_citations_round_trip():
    store = SqliteMetadataStore()
    store.record(rec("a", resolved=("art. 3º da Lei 9", "art. 4º")))

    assert store.records(STATUTE)["a"].resolved == ("art. 3º da Lei 9", "art. 4º")


def test_a_database_with_the_old_statute_id_column_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE enrichment_record (chunk_id TEXT PRIMARY KEY, lei_id TEXT NOT NULL, "
        "key TEXT NOT NULL, status TEXT NOT NULL, dropped INTEGER NOT NULL, skipped TEXT, "
        "resolved TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL)"
    )
    old.execute("INSERT INTO enrichment_record VALUES ('a', 'lei', 'k1', 'ok', 0, NULL, '[]', 't')")
    old.commit()
    old.close()

    store = SqliteMetadataStore(path)

    assert store.pending("lei", {"a": "k1"}) == []
    store.record(rec("b", statute="STJ"))
    assert set(store.records("STJ")) == {"b"}
