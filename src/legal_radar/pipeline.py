"""Pipeline entrypoint: parse a lei, tag dispositivos with conceitos, write the graph."""

from legal_radar.domain import Conceito, ConceptLink, GraphBatch
from legal_radar.parser import parse_lei
from legal_radar.ports import GraphStore, Provider

PROMPT = "Return the conceito id (snake_case) that this dispositivo is about:\n{text}"


def run(raw_lei: str, provider: Provider, store: GraphStore) -> GraphBatch:
    lei, dispositivos = parse_lei(raw_lei)
    links = [
        ConceptLink(d.id, provider.complete(PROMPT.format(text=d.text)).text.strip())
        for d in dispositivos
    ]
    conceitos = [Conceito(cid) for cid in sorted({link.conceito_id for link in links})]
    batch = GraphBatch(lei, dispositivos, conceitos, links)
    store.write(batch)
    return batch
