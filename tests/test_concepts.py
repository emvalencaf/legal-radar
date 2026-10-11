import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.concepts import (
    CATEGORIES,
    VocabularyError,
    draft_candidates,
    load_vocabulary,
    parse_vocabulary,
)
from legal_radar.llm import Completion


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


def test_committed_vocabulary_is_valid_and_sized():
    from legal_radar.concepts import VOCABULARY_PATHS

    for path in VOCABULARY_PATHS.values():
        vocabulary = load_vocabulary(path)
        assert 25 <= len(vocabulary.conceitos) <= 40
