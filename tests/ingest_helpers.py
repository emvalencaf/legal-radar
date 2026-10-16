from pathlib import Path

from legal_radar.domain.model import GraphBatch, Jurisprudencia, Relation
from legal_radar.planalto import decode_html

FIXTURES = Path(__file__).parent / "fixtures"
CC = "urn:lex:br:federal:lei:2002-01-10;10406"
CDC = "urn:lex:br:federal:lei:1990-09-11;8078"
CC_AGENT = "http://legislacao.planalto.gov.br/legisla/legislacao.nsf/websearch?openagent&tipo=LEI&codigo=10.406&ementa=2&data=20020110"


class FakePages:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        return self.pages[url]


class MemoryStore:
    def __init__(self):
        self.batches: list[GraphBatch] = []
        self.jurisprudencia: list[list[Jurisprudencia]] = []
        self.decision_relations: list[Relation] = []
        self.resolved: list[tuple[str, list[str]]] = []
        self.replaced: list[tuple[str, list[Relation]]] = []

    def write(self, batch: GraphBatch) -> None:
        self.batches.append(batch)

    def replace_llm_relations(self, chunk_id: str, relations: list[Relation]) -> None:
        self.replaced.append((chunk_id, relations))

    def resolve_citations(self, chunk_id: str, citations: list[str]) -> None:
        self.resolved.append((chunk_id, citations))

    def write_jurisprudencia(
        self, items: list[Jurisprudencia], relations: list[Relation] = ()
    ) -> None:
        self.jurisprudencia.append(items)
        self.decision_relations += relations


def read(path: str) -> str:
    return decode_html((FIXTURES / path).read_bytes())


def lexml_pages() -> FakePages:
    return FakePages(
        {
            "https://www.lexml.gov.br/busca/search?keyword=lei+10406+2002+c%C3%B3digo+civil": read(
                "lexml/search_cc.html"
            ),
            f"https://www.lexml.gov.br/urn/{CC}": read("lexml/urn_cc.html"),
            f"https://www.lexml.gov.br/urn/{CDC}": read("lexml/urn_cdc.html"),
        }
    )
