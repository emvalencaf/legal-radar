"""Jurisprudência ingestion: pinned seed precedents plus the top hits per court -> graph."""

from dataclasses import dataclass, field

from legal_radar.domain import Jurisprudencia
from legal_radar.ports import GraphStore, JurisprudenciaFetcher

TOP_HITS = 5
SEED_WINDOW = 10  # results scanned for a pinned seed's native id


@dataclass(frozen=True)
class Seed:
    court: str
    native_id: str
    query: str  # narrow enough that the pinned decision is among its first results


SEEDS = [
    Seed("STJ", "202001090402", "REsp 1873811"),  # Tema Repetitivo 1210, core (CC art. 50)
    Seed("STF", "sjur550030", 'titulo:"RE 1387795"'),  # Tema 1232, tangential
]
SEARCHES = {
    "STF": "desconsideração personalidade jurídica art. 50 código civil",
    "STJ": "desconsideração personalidade jurídica art. 50",
}


@dataclass
class JurisprudenciaReport:
    ingested: int = 0
    failed: dict[str, str] = field(default_factory=dict)  # seed id or court -> reason

    def render(self) -> str:
        lines = [f"ingested {self.ingested} jurisprudência nodes"]
        lines += [f"failed {key}: {reason}" for key, reason in self.failed.items()]
        return "\n".join(lines)


def ingest_jurisprudencia(
    fetchers: dict[str, JurisprudenciaFetcher],
    store: GraphStore,
    seeds: list[Seed] = SEEDS,
    searches: dict[str, str] = SEARCHES,
) -> JurisprudenciaReport:
    report = JurisprudenciaReport()
    items: dict[str, Jurisprudencia] = {}
    for seed in seeds:
        key = f"{seed.court}:{seed.native_id}"
        try:
            hits = fetchers[seed.court].search(seed.query, SEED_WINDOW)
        except Exception as error:  # a flaky court must not stop the other sources
            report.failed[key] = str(error)
            continue
        if seed_hit := next((h for h in hits if h.id == key), None):
            items[key] = seed_hit
        else:
            report.failed[key] = f"not among the first {SEED_WINDOW} results of {seed.query!r}"
    for court, query in searches.items():
        try:
            for hit in fetchers[court].search(query, TOP_HITS)[:TOP_HITS]:
                items.setdefault(hit.id, hit)
        except Exception as error:
            report.failed[court] = str(error)
    if items:
        store.write_jurisprudencia(list(items.values()))
    report.ingested = len(items)
    return report
