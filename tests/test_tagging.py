import json
from pathlib import Path

import pytest

from legal_radar.adapters.fake_provider import FakeProvider
from legal_radar.llm import Completion
from legal_radar.pipeline import TaggingError, run
from legal_radar.prompts import PromptError, refresh

RAW = (Path(__file__).parent / "fixtures" / "mini_lei.txt").read_text(encoding="utf-8")
SCHEMA = {
    "title": "dispositivo_concept",
    "type": "object",
    "properties": {"conceito_id": {"type": "string", "enum": ["placeholder"]}},
    "required": ["conceito_id"],
    "additionalProperties": False,
}


class Store:
    def write(self, batch):
        self.batch = batch


def lock(schema=SCHEMA):
    return refresh({"dispositivo-concept": "c1"}, lambda n, c: ("Tag:\n{text}", schema))


def answer(conceito_id):
    return Completion(json.dumps({"conceito_id": conceito_id}))


def test_pipeline_sends_the_pinned_schema_with_the_vocabulary_ids_as_enum():
    seen = []
    provider = FakeProvider()
    complete = provider.complete
    provider.complete = lambda prompt, params=None: seen.append(params) or complete(prompt, params)

    run(RAW, provider, Store(), lock(), conceito_ids=["decisao_judicial", "abuso_da_personalidade"])

    enum = seen[0].response_schema["properties"]["conceito_id"]["enum"]
    assert enum == ["abuso_da_personalidade", "decisao_judicial"]
    assert SCHEMA["properties"]["conceito_id"]["enum"] == ["placeholder"]


def test_pipeline_parses_the_structured_reply_into_the_conceito_id():
    store = Store()
    run(RAW, FakeProvider(), store, lock())
    assert {link.conceito_id for link in store.batch.links} == {
        "abuso_da_personalidade",
        "decisao_judicial",
    }


@pytest.mark.parametrize(
    "reply",
    [
        Completion("abuso_da_personalidade"),
        Completion("[]"),
        Completion(json.dumps({"outro": "x"})),
        Completion(json.dumps({"conceito_id": 3})),
        Completion(json.dumps({"conceito_id": ""})),
        answer("fora_do_vocabulario"),
    ],
)
def test_an_answer_outside_the_schema_fails_loudly_and_writes_nothing(reply):
    store = Store()
    with pytest.raises(TaggingError):
        run(RAW, FakeProvider(script=[reply]), store, lock(), conceito_ids=["decisao_judicial"])
    assert not hasattr(store, "batch")


def test_a_prompt_without_a_pinned_schema_is_refused():
    with pytest.raises(PromptError):
        run(RAW, FakeProvider(), Store(), lock(schema=None))
