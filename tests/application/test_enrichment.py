from dataclasses import replace

from legal_radar.adapters.prompt_lock import refresh
from legal_radar.application.concepts import Concept, Vocabulary
from legal_radar.application.enrichment import enrichment_key

CONCEPT = Concept(
    id="abuso",
    label="Abuso",
    aliases=(),
    instructions="Quando o texto trata de abuso.",
    category="TEORIA",
)
VOCABULARY = Vocabulary("direito_civil", (CONCEPT,))


def lock(commit="c1", template="t"):
    return refresh({"dispositivo-enrichment": commit}, lambda n, c: (template, None))


def key(text="art. 50", vocabulary=VOCABULARY, prompts=None, version="1"):
    return enrichment_key(text, vocabulary, prompts or lock(), version)


def test_key_is_stable_for_identical_inputs():
    assert key() == key()


def test_each_ingredient_changes_the_key():
    changed_vocabulary = Vocabulary("direito_civil", (replace(CONCEPT, label="Outro"),))
    keys = {
        key(),
        key(text="art. 51"),
        key(vocabulary=changed_vocabulary),
        key(prompts=lock(template="new")),
        key(prompts=lock(commit="c2")),
        key(version="2"),
    }
    assert len(keys) == 6


def test_provenance_only_vocabulary_edits_keep_the_key():
    reviewed = Vocabulary("direito_civil", (replace(CONCEPT, reviewed_by="edson"),))
    assert key(vocabulary=reviewed) == key()
