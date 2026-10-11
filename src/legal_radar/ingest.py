"""Lei ingestion: LexML URN -> Planalto page -> legal-document AST -> graph."""

from dataclasses import dataclass, field

from legal_radar.anchors import AnchorLei
from legal_radar.domain import GraphBatch, Lei
from legal_radar.lexml import LexmlError, resolve_urn, search_urn
from legal_radar.planalto import parse_planalto
from legal_radar.ports import GraphStore, PageSource


@dataclass
class IngestionReport:
    ingested: dict[str, int] = field(default_factory=dict)  # urn -> dispositivo count
    skipped: dict[str, list[str]] = field(default_factory=dict)  # urn -> non-Planalto hosts
    failed: dict[str, str] = field(default_factory=dict)  # keyword -> reason

    def render(self) -> str:
        lines = [f"ingested {urn}: {n} dispositivos" for urn, n in self.ingested.items()]
        lines += [
            f"skipped {urn}: no Planalto text (destinations: {', '.join(hosts) or 'none'})"
            for urn, hosts in self.skipped.items()
        ]
        lines += [f"failed {keyword!r}: {reason}" for keyword, reason in self.failed.items()]
        return "\n".join(lines)


def ingest(
    anchors: list[AnchorLei], lexml: PageSource, planalto: PageSource, store: GraphStore
) -> IngestionReport:
    report = IngestionReport()
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
        store.write(GraphBatch(Lei(urn, page.title, page.planalto_url), dispositivos, [], []))
        report.ingested[urn] = len(dispositivos)
    return report
