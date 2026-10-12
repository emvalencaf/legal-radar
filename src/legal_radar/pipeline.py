"""Pipeline entrypoint: parse a lei, tag dispositivos with conceitos, write the graph."""

from legal_radar.domain import Conceito, ConceptLink, GraphBatch
from legal_radar.llm import CompletionParams
from legal_radar.parser import parse_lei
from legal_radar.ports import GraphStore, Provider
from legal_radar.prompts import PromptLock, default_lock


def run(
    raw_lei: str, provider: Provider, store: GraphStore, lock: PromptLock | None = None
) -> GraphBatch:
    lock = lock or default_lock()
    params = CompletionParams(
        pipeline_step="tag", prompt_snapshot=lock.prompt_hash("dispositivo-concept")
    )
    lei, dispositivos = parse_lei(raw_lei)
    links = [
        ConceptLink(
            d.id,
            provider.complete(lock.render("dispositivo-concept", text=d.text), params).text.strip(),
        )
        for d in dispositivos
    ]
    conceitos = [Conceito(cid) for cid in sorted({link.conceito_id for link in links})]
    batch = GraphBatch(lei, dispositivos, conceitos, links)
    store.write(batch)
    return batch
