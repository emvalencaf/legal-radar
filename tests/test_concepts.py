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


def concept_json(**overrides) -> str:
    import json

    entry = {
        "id": "x",
        "label": "L",
        "aliases": [],
        "instructions": "i",
        "category": "ATOR",
        "sources": [],
        **overrides,
    }
    return json.dumps({"conceitos": [entry]})


def count_json(n=1) -> str:
    return f'{{"quantidade": {n}}}'


def test_draft_candidates_counts_then_extracts_that_many():
    provider = FakeProvider(
        script=[Completion(count_json(7)), Completion(concept_json(), provider="g", model="m")]
    )
    corpus = ["[CC#art50]\nabuso", "[STJ:1]\nTema 1210"]

    draft = draft_candidates("desconsideração", corpus, provider)

    assert [c["id"] for c in draft.conceitos] == ["x"]
    assert (draft.model, draft.expected) == ("g/m", 7)
    count_prompt, extract_prompt = provider.calls
    assert "Tema 1210" in count_prompt and "Tema 1210" in extract_prompt
    assert "7" not in count_prompt and "exatamente esses 7 conceitos" in extract_prompt


def test_each_step_sends_its_own_schema_and_pipeline_step():
    seen = []
    provider = FakeProvider(script=[Completion(count_json(2)), Completion(concept_json())])
    complete = provider.complete
    provider.complete = lambda prompt, params=None: seen.append(params) or complete(prompt, params)

    draft_candidates("a", ["[x]\nt"], provider)

    count, extract = seen
    assert (count.pipeline_step, extract.pipeline_step) == (
        "concept_vocabulary_count",
        "concept_vocabulary_draft",
    )
    assert count.response_schema["required"] == ["quantidade"]
    assert extract.response_schema["required"] == ["conceitos"]


def test_schemas_describe_every_field_and_limit_categories_and_sources():
    from legal_radar.concepts import extract_schema
    from legal_radar.prompts import default_lock

    lock = default_lock()

    def described(schema):
        assert schema["description"]
        for prop in schema.get("properties", {}).values():
            assert prop["description"], prop
            described_items = prop.get("items")
            if isinstance(described_items, dict) and described_items.get("type") == "object":
                described(described_items)

    described(lock.schema("concepts-count"))
    described(extract_schema(lock, ["a"]))
    concept = extract_schema(lock, ["b", "a"])["properties"]["conceitos"]["items"]
    assert concept["properties"]["category"]["enum"] == list(CATEGORIES)
    assert concept["properties"]["sources"]["items"]["enum"] == ["a", "b"]
    assert concept["additionalProperties"] is False
    assert set(concept["required"]) == set(concept["properties"])


@pytest.mark.parametrize(
    "script",
    [
        ["not json"],
        ["{}"],
        [count_json(0)],
        ['{"quantidade": "3"}'],
        ['{"quantidade": true}'],
        [count_json(2), "not json"],
        [count_json(2), '{"conceitos": 3}'],
    ],
)
def test_draft_candidates_rejects_an_answer_off_the_schema(script):
    provider = FakeProvider(script=[Completion(text) for text in script])

    with pytest.raises(VocabularyError):
        draft_candidates("a", ["[x]\nt"], provider)


def test_with_assunto_reports_a_count_mismatch():
    from legal_radar.concepts import Draft, with_assunto

    entry = draft_of().conceitos
    assert with_assunto("a", Draft(entry, "fake/m", expected=1))[1] is None
    assert "counted 3 concepts but extracted 1" in with_assunto("a", Draft(entry, "f/m", 3))[1]


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


def draft_of(**overrides):
    from legal_radar.concepts import Draft

    entry = {
        "id": "x",
        "label": "L",
        "aliases": [],
        "instructions": "i",
        "category": "ATOR",
        "sources": [],
        **overrides,
    }
    return Draft([entry], "fake/m")


def test_with_assunto_builds_a_loadable_draft_and_reports_when_it_does_not():
    from legal_radar.concepts import Draft, with_assunto

    text, error = with_assunto("a b", draft_of())
    assert text.startswith("assunto: a b\n") and error is None

    _, error = with_assunto("a b", Draft([], "fake/m"))
    assert "non-empty list" in error


def provenance_yaml(status=None, **entry) -> str:
    import yaml

    base = {"id": "x", "label": "L", "instructions": "i", "category": "ATOR", **entry}
    document = {"assunto": "a", "conceitos": [base]}
    if status:
        document["status"] = status
    return yaml.safe_dump(document, allow_unicode=True)


def test_provenance_is_loaded_but_never_changes_the_hash():
    plain = parse_vocabulary(provenance_yaml())
    reviewed = parse_vocabulary(
        provenance_yaml(origin="llm", model="g/m", reviewed_by="Edson", reviewed_on="2026-10-11")
    )

    concept = reviewed.conceitos[0]
    assert (concept.origin, concept.reviewed_by, concept.reviewed_on) == (
        "llm",
        "Edson",
        "2026-10-11",
    )
    assert concept.reviewed and not plain.conceitos[0].reviewed
    assert reviewed.hash == plain.hash


@pytest.mark.parametrize(
    "entry",
    [
        {"origin": "robot"},
        {"reviewed_by": "Edson"},
        {"reviewed_on": "2026-10-11"},
        {"reviewed_by": "Edson", "reviewed_on": "ontem"},
        {"reviewed_by": " ", "reviewed_on": "2026-10-11"},
    ],
)
def test_rejects_invalid_provenance(entry):
    with pytest.raises(VocabularyError):
        parse_vocabulary(provenance_yaml(**entry))


def test_status_defaults_to_draft_and_curated_needs_every_concept_reviewed():
    assert parse_vocabulary(provenance_yaml()).status == "draft"
    with pytest.raises(VocabularyError, match="status"):
        parse_vocabulary(provenance_yaml(status="done"))
    with pytest.raises(VocabularyError, match="every concept reviewed"):
        parse_vocabulary(provenance_yaml(status="curated"))
    reviewed = {"reviewed_by": "Edson", "reviewed_on": "2026-10-11"}
    assert parse_vocabulary(provenance_yaml(status="curated", **reviewed)).status == "curated"


def test_a_draft_vocabulary_only_warns_when_loaded(caplog, monkeypatch, tmp_path):
    from legal_radar import concepts

    path = tmp_path / "v.yml"
    path.write_text(valid_yaml().replace("assunto: a", "assunto: b"), encoding="utf-8")
    monkeypatch.setitem(concepts.VOCABULARY_PATHS, "b", path)

    with caplog.at_level("WARNING"):
        vocabulary = concepts.load_registered("b")

    assert vocabulary.status == "draft"
    assert "is a draft: 1 of 1 concepts not reviewed" in caplog.text


def test_the_committed_vocabulary_is_curated_and_loads_without_a_warning(caplog):
    from legal_radar.concepts import VOCABULARY_PATHS, load_registered

    with caplog.at_level("WARNING"):
        for assunto in VOCABULARY_PATHS:
            vocabulary = load_registered(assunto)
            assert vocabulary.status == "curated"
            assert all(c.reviewed for c in vocabulary.conceitos)

    assert "is a draft" not in caplog.text


def test_with_assunto_marks_the_draft_as_llm_origin():
    from datetime import date

    from legal_radar.concepts import with_assunto

    text, error = with_assunto("a", draft_of())

    assert error is None
    vocabulary = parse_vocabulary(text)
    concept = vocabulary.conceitos[0]
    assert vocabulary.status == "draft" and concept.origin == "llm"
    assert concept.model == "fake/m"
    assert concept.created_at == date.today().isoformat()


def test_sources_are_loaded_but_never_change_the_hash():
    plain = parse_vocabulary(provenance_yaml())
    cited = parse_vocabulary(provenance_yaml(sources=["STJ:1", "lei#art50"]))

    assert cited.conceitos[0].sources == ("STJ:1", "lei#art50")
    assert cited.hash == plain.hash
    for bad in ("STJ:1", [""], [1]):
        with pytest.raises(VocabularyError):
            parse_vocabulary(provenance_yaml(sources=bad))


def test_with_assunto_reports_sources_missing_from_the_corpus():
    from legal_radar.concepts import corpus_ids, with_assunto

    ids = corpus_ids(["[STJ:1]\nementa", "[lei#art50]\ntexto"])
    assert ids == {"STJ:1", "lei#art50"}

    assert with_assunto("a", draft_of(sources=["STJ:1"]), ids)[1] is None
    assert "STF:9" in with_assunto("a", draft_of(sources=["STJ:1", "STF:9"]), ids)[1]


def test_timestamps_are_loaded_validated_and_outside_the_hash():
    plain = parse_vocabulary(provenance_yaml())
    stamped = parse_vocabulary(provenance_yaml(created_at="2026-10-11", updated_at="2026-10-12"))

    assert (stamped.conceitos[0].created_at, stamped.conceitos[0].updated_at) == (
        "2026-10-11",
        "2026-10-12",
    )
    assert stamped.hash == plain.hash
    for bad in (
        {"created_at": "ontem"},
        {"updated_at": "2026-10-12"},
        {"created_at": "2026-10-12", "updated_at": "2026-10-11"},
    ):
        with pytest.raises(VocabularyError):
            parse_vocabulary(provenance_yaml(**bad))


@pytest.mark.parametrize(
    "entry",
    [
        {"origin": "llm"},
        {"origin": "llm", "model": " "},
        {"origin": "human", "model": "g/m"},
        {"model": "g/m"},
    ],
)
def test_model_goes_with_llm_origin_only(entry):
    with pytest.raises(VocabularyError):
        parse_vocabulary(provenance_yaml(**entry))


def test_model_is_provenance_outside_the_hash():
    plain = parse_vocabulary(provenance_yaml())
    drafted = parse_vocabulary(provenance_yaml(origin="llm", model="gemini/flash"))

    assert drafted.conceitos[0].model == "gemini/flash"
    assert drafted.hash == plain.hash
