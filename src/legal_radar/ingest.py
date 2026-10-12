"""Lei ingestion: LexML URN -> Planalto page -> legal-document AST -> graph."""

from dataclasses import dataclass, field

from legal_radar.anchors import AnchorLei
from legal_radar.domain import Dispositivo, GraphBatch, Lei, Relation
from legal_radar.lexml import LexmlError, resolve_urn, search_urn
from legal_radar.planalto import parse_planalto
from legal_radar.ports import GraphStore, PageSource
from legal_radar.relations import UrnResolver, extract_relations


@dataclass
class IngestionReport:
    ingested: dict[str, int] = field(default_factory=dict)  # urn -> dispositivo count
    skipped: dict[str, list[str]] = field(default_factory=dict)  # urn -> non-Planalto hosts
    failed: dict[str, str] = field(default_factory=dict)  # keyword -> reason
    relations: dict[str, int] = field(default_factory=dict)  # urn -> edges extracted by rules
    needs_llm: dict[str, int] = field(default_factory=dict)  # urn -> chunks left for the enricher
    dropped: dict[str, int] = field(default_factory=dict)  # urn -> items failing validation

    def render(self) -> str:
        lines = [
            f"ingested {urn}: {n} dispositivos, {self.relations.get(urn, 0)} relations, "
            f"{self.needs_llm.get(urn, 0)} for the LLM, {self.dropped.get(urn, 0)} dropped"
            for urn, n in self.ingested.items()
        ]
        lines += [
            f"skipped {urn}: no Planalto text (destinations: {', '.join(hosts) or 'none'})"
            for urn, hosts in self.skipped.items()
        ]
        lines += [f"failed {keyword!r}: {reason}" for keyword, reason in self.failed.items()]
        return "\n".join(lines)


def ingest(
    anchors: list[AnchorLei],
    lexml: PageSource,
    planalto: PageSource,
    store: GraphStore,
    resolver: UrnResolver | None = None,
) -> IngestionReport:
    """Parse every anchor lei, extract its relations, then load them.

    Relations are extracted once all leis are parsed: a citation of a lei of this run is checked
    against its dispositivos, and one of any other lei is a stub (LOW).
    """
    report = IngestionReport()
    parsed: list[tuple[Lei, list[Dispositivo]]] = []
    for anchor in anchors:
        try:
            urn = search_urn(lexml, anchor.keyword, anchor.numero, anchor.ano)
            page = resolve_urn(lexml, urn)
            if page.planalto_url is None:
                report.skipped[urn] = page.destinations
                continue
            dispositivos = parse_planalto(planalto.get(page.planalto_url), urn)
        except LexmlError as error:
            report.failed[anchor.keyword] = str(error)
            continue
        parsed.append((Lei(urn, page.title, page.planalto_url), dispositivos))

    in_graph = {lei.id: {d.id for d in dispositivos} for lei, dispositivos in parsed}
    for lei, dispositivos in parsed:
        relations: list[Relation] = []
        for d in dispositivos:
            extraction = extract_relations(d, resolver, in_graph)
            relations += extraction.relations
            report.needs_llm[lei.id] = report.needs_llm.get(lei.id, 0) + extraction.needs_enrichment
            report.dropped[lei.id] = report.dropped.get(lei.id, 0) + extraction.dropped
        store.write(GraphBatch(lei, dispositivos, [], [], relations))
        report.ingested[lei.id] = len(dispositivos)
        report.relations[lei.id] = len(relations)
    return report
