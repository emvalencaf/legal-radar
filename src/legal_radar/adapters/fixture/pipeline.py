"""Pipeline entrypoint: parse a lei, tag dispositivos with conceitos, write the graph."""

import copy
import json

import jsonschema

from legal_radar.adapters.fixture.parser import parse_statute
from legal_radar.adapters.prompt_lock import default_lock
from legal_radar.application.ports import GraphStore, Provider
from legal_radar.domain.llm import CompletionParams, content_hash
from legal_radar.domain.model import ConceptLink, ConceptNode, GraphBatch
from legal_radar.domain.prompts import PromptError, PromptLock

TAG_PROMPT = "dispositivo-concept"
TAG_SCHEMA = {  # published to the Hub as `dispositivo-concept`'s structured output
    "title": "dispositivo_concept",
    "type": "object",
    "description": "O conceito jurídico de que o dispositivo trata.",
    "properties": {
        "conceito_id": {
            "type": "string",
            "description": "Id (snake_case) de um conceito do vocabulário do assunto.",
            "enum": ["placeholder"],  # the real ids are filled in at run time
        }
    },
    "required": ["conceito_id"],
    "additionalProperties": False,
}


class TaggingError(ValueError):
    """The LLM's tagging reply is outside the pinned schema."""


def tag_schema(lock: PromptLock, concept_ids: list[str] | None) -> dict:
    """The pinned schema; the Hub stores it static, so the vocabulary's ids fill its enum here.
    Without `concept_ids` the enum is dropped and any non-empty id is accepted."""
    schema = lock.schema(TAG_PROMPT)
    if schema is None:
        raise PromptError(f"prompt {TAG_PROMPT!r} has no pinned schema: run `refresh-prompts`")
    schema = copy.deepcopy(schema)
    try:
        concept = schema["properties"]["conceito_id"]
    except (KeyError, TypeError) as error:
        raise PromptError(f"prompt {TAG_PROMPT!r}: its schema has no conceito_id") from error
    if concept_ids is None:
        concept.pop("enum", None)  # the pinned enum is a placeholder
    elif not concept_ids:
        raise ValueError("conceito_ids is empty: no answer could pass the schema")
    else:
        concept["enum"] = sorted(concept_ids)
    return schema


def parse_tag(text: str, schema: dict) -> str:
    """The conceito id of a reply, which must validate against `schema`."""
    try:
        reply = json.loads(text)
        jsonschema.validate(reply, schema)
    except (ValueError, jsonschema.ValidationError) as error:
        raise TaggingError(f"the LLM did not answer the tagging schema: {error}") from error
    concept_id = reply["conceito_id"]
    if not concept_id.strip():
        raise TaggingError("the LLM answered an empty conceito_id")
    return concept_id


def run(
    raw_statute: str,
    provider: Provider,
    store: GraphStore,
    lock: PromptLock | None = None,
    concept_ids: list[str] | None = None,
) -> GraphBatch:
    """Tags each dispositivo with one conceito; with `conceito_ids`, only those are accepted."""
    lock = lock or default_lock()
    schema = tag_schema(lock, concept_ids)
    params = CompletionParams(
        pipeline_step="tag",
        response_schema=schema,
        prompt_snapshot=content_hash(  # the schema sent, with the vocabulary's enum, not the pinned
            {"prompt": lock.prompt_hash(TAG_PROMPT), "schema": schema}
        ),
    )
    statute, provisions = parse_statute(raw_statute)
    links = [
        ConceptLink(
            d.id,
            parse_tag(provider.complete(lock.render(TAG_PROMPT, text=d.text), params).text, schema),
        )
        for d in provisions
    ]
    concepts = [ConceptNode(cid) for cid in sorted({link.concept_id for link in links})]
    batch = GraphBatch(statute, provisions, concepts, links)
    store.write(batch)
    return batch
