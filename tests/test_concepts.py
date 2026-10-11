import pytest
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.concepts import (
    CATEGORIES,
    VocabularyError,
    draft_candidates,
    load_vocabulary,
    parse_vocabulary,
)
from legal_radar.llm import Completion


@pytest.fixture(scope="module")
def neo4j():
    with Neo4jContainer("neo4j:5-community") as container:
        yield container


@pytest.fixture
def driver(neo4j):
    driver = GraphDatabase.driver(neo4j.get_connection_url(), auth=("neo4j", neo4j.password))
    driver.execute_query("MATCH (n) DETACH DELETE n")
    yield driver
    driver.close()


def valid_yaml(**overrides) -> str:
    entry = {
        "id": "abuso_da_personalidade",
        "label": "Abuso",
        "aliases": ["desvio"],
        "instructions": "Use quando houver abuso.",
        "category": "REQUISITO",
        **overrides,
    }
    import yaml

    return yaml.safe_dump({"assunto": "a", "conceitos": [entry]}, allow_unicode=True)


def test_loads_a_valid_vocabulary():
    vocabulary = parse_vocabulary(valid_yaml())

    assert vocabulary.assunto == "a"
    assert [c.id for c in vocabulary.conceitos] == ["abuso_da_personalidade"]
    assert vocabulary.conceitos[0].aliases == ("desvio",)
    assert "REQUISITO" in CATEGORIES


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "Abuso"},
        {"id": "sócio"},
        {"id": "abuso-da"},
        {"id": ""},
        {"category": "RESTRICAO"},
        {"label": ""},
        {"instructions": ""},
        {"aliases": "desvio"},
        {"aliases": [""]},
    ],
)
def test_rejects_invalid_entries(overrides):
    with pytest.raises(VocabularyError):
        parse_vocabulary(valid_yaml(**overrides))


def test_rejects_duplicate_ids_and_aliases_shared_across_concepts():
    import yaml

    base = {"label": "L", "aliases": [], "instructions": "i", "category": "ATOR"}
    twice = {"assunto": "a", "conceitos": [{"id": "x", **base}, {"id": "x", **base}]}
    with pytest.raises(VocabularyError, match="duplicate"):
        parse_vocabulary(yaml.safe_dump(twice))
    shared = {
        "assunto": "a",
        "conceitos": [
            {"id": "x", **base, "aliases": ["Termo"]},
            {"id": "y", **base, "label": "M", "aliases": ["termo"]},
        ],
    }
    with pytest.raises(VocabularyError, match="termo"):
        parse_vocabulary(yaml.safe_dump(shared))


@pytest.mark.parametrize("text", ["", "- a", "assunto: a", "assunto: a\nconceitos: []"])
def test_rejects_malformed_documents(text):
    with pytest.raises(VocabularyError):
        parse_vocabulary(text)


def test_hash_is_stable_and_ignores_order_and_formatting():
    import yaml

    a = parse_vocabulary(valid_yaml())
    assert a.hash == parse_vocabulary(valid_yaml()).hash
    assert a.hash.startswith("sha256:")

    base = {"label": "L", "aliases": [], "instructions": "i", "category": "ATOR"}
    one = [{"id": "x", **base}, {"id": "y", **base, "label": "M"}]
    doc = lambda items: yaml.safe_dump({"assunto": "a", "conceitos": items})  # noqa: E731
    assert parse_vocabulary(doc(one)).hash == parse_vocabulary(doc(one[::-1])).hash


def test_hash_changes_when_a_concept_changes():
    assert parse_vocabulary(valid_yaml()).hash != parse_vocabulary(valid_yaml(label="Outro")).hash


def test_load_vocabulary_reads_a_file(tmp_path):
    path = tmp_path / "v.yml"
    path.write_text(valid_yaml(), encoding="utf-8")

    assert load_vocabulary(path) == parse_vocabulary(valid_yaml())


def test_draft_candidates_prompts_with_the_corpus_and_strips_fences():
    provider = FakeProvider(script=[Completion("```yaml\nconceitos: []\n```")])

    draft = draft_candidates("desconsideração", ["CC art. 50 abuso", "Tema 1210"], provider)

    assert draft == "conceitos: []\n"
    prompt = provider.calls[0]
    assert "CC art. 50 abuso" in prompt and "Tema 1210" in prompt
    assert "DIREITO" in prompt and "snake_case" in prompt


def test_every_anchor_assunto_has_a_valid_registered_vocabulary():
    from legal_radar.anchors import ANCHORS
    from legal_radar.concepts import VOCABULARY_PATHS, load_registered

    assert set(ANCHORS) == set(VOCABULARY_PATHS)
    for assunto in VOCABULARY_PATHS:
        assert 25 <= len(load_registered(assunto).conceitos) <= 40


def test_load_registered_rejects_unknown_and_mismatched_assuntos(monkeypatch, tmp_path):
    from legal_radar import concepts

    with pytest.raises(VocabularyError, match="no vocabulary registered"):
        concepts.load_registered("outro")

    path = tmp_path / "v.yml"
    path.write_text(valid_yaml(), encoding="utf-8")  # declares assunto "a"
    monkeypatch.setitem(concepts.VOCABULARY_PATHS, "b", path)
    with pytest.raises(VocabularyError, match="declares assunto 'a'"):
        concepts.load_registered("b")


def test_graph_corpus_reads_the_seed_dispositivos_and_all_jurisprudencia(driver):
    from legal_radar.concepts import CORPUS_ROOTS, graph_corpus

    root = CORPUS_ROOTS[0]
    driver.execute_query(
        "UNWIND $ids AS id CREATE (:Dispositivo {id: id, text: 'texto ' + id})",
        ids=[root, root + "_par1", root + "0", "outro#art1"],
    )
    driver.execute_query(
        "CREATE (:Jurisprudencia {id: 'STJ:1', ementa: 'ementa', tese: 'tese'}),"
        " (:Jurisprudencia {id: 'STF:2', ementa: 'so ementa'})"
    )

    corpus = graph_corpus(driver)

    assert [entry.split("\n")[0] for entry in corpus] == [
        "[STF:2]",
        "[STJ:1]",
        f"[{root}]",
        f"[{root}_par1]",
    ]
    assert "ementa\ntese" in corpus[1]


def test_with_assunto_prefixes_and_reports_whether_the_draft_loads():
    from legal_radar.concepts import with_assunto

    draft = "conceitos:\n  - {id: x, label: L, instructions: i, category: ATOR}\n"

    text, error = with_assunto("a b", draft)
    assert text.startswith("assunto: a b\n") and error is None

    _, error = with_assunto("a b", "conceitos: []\n")
    assert "non-empty list" in error
