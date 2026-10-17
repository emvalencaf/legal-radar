import pytest

from legal_radar.adapters.sqlite_vectors import SqliteVectorStore
from legal_radar.domain.model import StoredVector


def test_saved_vectors_come_back_and_survive_reopening(tmp_path):
    path = tmp_path / "idx" / "v.sqlite"
    store = SqliteVectorStore(path)
    store.save({"a": StoredVector("h1", "m", [0.5, 0.25]), "b": StoredVector("h2", "m", [1.0])})
    store.close()

    loaded = SqliteVectorStore(path).load()

    assert set(loaded) == {"a", "b"}
    assert (loaded["a"].text_hash, loaded["a"].model) == ("h1", "m")
    assert loaded["a"].vector == pytest.approx([0.5, 0.25])


def test_saving_again_replaces_the_vector():
    store = SqliteVectorStore()
    store.save({"a": StoredVector("h1", "m", [1.0])})
    store.save({"a": StoredVector("h2", "m2", [2.0])})

    (row,) = store.load().values()

    assert (row.text_hash, row.model, row.vector) == ("h2", "m2", [2.0])
