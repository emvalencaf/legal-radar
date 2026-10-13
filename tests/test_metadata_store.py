from legal_radar.adapters.sqlite_metadata import SqliteMetadataStore
from legal_radar.domain import EnrichmentRecord, EnrichmentStatus

LEI = "urn:lex:br:federal:lei:2002-01-10;10406"


def rec(chunk, key="k1", status=EnrichmentStatus.OK, lei=LEI, **kwargs):
    return EnrichmentRecord(chunk, lei, key, status, **kwargs)


def test_chunk_without_a_record_is_pending():
    assert SqliteMetadataStore().pending(LEI, {"a": "k1", "b": "k1"}) == ["a", "b"]


def test_ok_record_with_the_same_key_is_not_pending():
    store = SqliteMetadataStore()
    store.record(rec("a"))

    assert store.pending(LEI, {"a": "k1", "b": "k1"}) == ["b"]


def test_changed_key_or_pending_status_returns_the_chunk_to_pending():
    store = SqliteMetadataStore()
    store.record(rec("a"))
    store.record(rec("b", status=EnrichmentStatus.PENDING))
    store.record(rec("c"))

    assert store.pending(LEI, {"a": "k2", "b": "k1", "c": "k1"}) == ["a", "b"]


def test_record_is_upserted_and_scoped_to_its_lei(tmp_path):
    path = tmp_path / "nested" / "meta.sqlite"
    store = SqliteMetadataStore(path)
    store.record(rec("a", dropped=2, skipped="too_long"))
    store.record(rec("a", key="k2", dropped=1))
    store.record(rec("z", lei="other"))
    store.close()

    assert SqliteMetadataStore(path).records(LEI) == {"a": rec("a", key="k2", dropped=1)}
