"""Pipeline entrypoint: parse a lei, tag dispositivos with conceitos, write the graph."""

import copy
import json

from legal_radar.domain import Conceito, ConceptLink, GraphBatch
from legal_radar.llm import CompletionParams
from legal_radar.parser import parse_lei
from legal_radar.ports import GraphStore, Provider
from legal_radar.prompts import PromptError, PromptLock, default_lock

TAG_PROMPT = "dispositivo-concept"


class TaggingError(ValueError):
    """The LLM's tagging reply is outside the pinned schema."""


def tag_schema(lock: PromptLock, conceito_ids: list[str] | None) -> dict:
    """The pinned schema; the Hub stores it static, so the vocabulary's ids fill its enum here."""
    schema = lock.schema(TAG_PROMPT)
    if schema is None:
        raise PromptError(f"prompt {TAG_PROMPT!r} has no pinned schema: run `refresh-prompts`")
    schema = copy.deepcopy(schema)
    conceito = schema["properties"]["conceito_id"]
    if conceito_ids is None:
        conceito.pop("enum", None)  # the pinned enum is a placeholder
    else:
        conceito["enum"] = sorted(conceito_ids)
    return schema


def parse_tag(text: str, schema: dict) -> str:
    try:
        conceito_id = json.loads(text)["conceito_id"]
    except (ValueError, KeyError, TypeError) as error:
        raise TaggingError(f"the LLM did not answer the tagging schema: {error!r}") from error
    if not isinstance(conceito_id, str) or not conceito_id.strip():
        raise TaggingError(f"the LLM answered conceito_id {conceito_id!r}")
    allowed = schema["properties"]["conceito_id"].get("enum")
    if allowed is not None and conceito_id not in allowed:
        raise TaggingError(f"the LLM answered conceito_id {conceito_id!r}, not in the vocabulary")
    return conceito_id


def run(
    raw_lei: str,
    provider: Provider,
    store: GraphStore,
    lock: PromptLock | None = None,
    conceito_ids: list[str] | None = None,
) -> GraphBatch:
    """Tags each dispositivo with one conceito; with `conceito_ids`, only those are accepted."""
    lock = lock or default_lock()
    schema = tag_schema(lock, conceito_ids)
    params = CompletionParams(
        pipeline_step="tag",
        response_schema=schema,
        prompt_snapshot=lock.prompt_hash(TAG_PROMPT),
    )
    lei, dispositivos = parse_lei(raw_lei)
    links = [
        ConceptLink(
            d.id,
            parse_tag(provider.complete(lock.render(TAG_PROMPT, text=d.text), params).text, schema),
        )
        for d in dispositivos
    ]
    conceitos = [Conceito(cid) for cid in sorted({link.conceito_id for link in links})]
    batch = GraphBatch(lei, dispositivos, conceitos, links)
    store.write(batch)
    return batch
