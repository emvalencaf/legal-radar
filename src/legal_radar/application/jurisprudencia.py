"""Jurisprudência ingestion: pinned seed precedents plus the top hits per court -> graph."""

from dataclasses import dataclass, field

from legal_radar.application.enricher import decision_texts, enrich_decision
from legal_radar.application.enrichment import DECISION_PROMPT, enrichment_key
from legal_radar.application.ingest import EnrichConfig, EnrichmentCounts
from legal_radar.application.ports import GraphStore, JurisprudenciaFetcher
from legal_radar.domain.llm import ProviderError
from legal_radar.domain.model import EnrichmentRecord, EnrichmentStatus, Jurisprudencia, Relation
from legal_radar.domain.relations import UrnResolver, extract_decision_relations

TOP_HITS = 5  # default number of top hits per court
SEED_WINDOW = 10  # results scanned for a pinned seed's native id


@dataclass(frozen=True)
class Seed:
    court: str
    native_id: str
    query: str  # narrow enough that the pinned decision is among its first results


@dataclass(frozen=True)
class JurisprudenciaSource:
    """Where an assunto's decisions come from: pinned seeds plus a search per court."""

    seeds: tuple[Seed, ...] = ()
    searches: dict[str, str] = field(default_factory=dict)  # court -> free-text query
    top_hits: int = TOP_HITS  # per court; 0 ingests only the seeds


JURISPRUDENCIA: dict[str, JurisprudenciaSource] = {
    "desconsideração da personalidade jurídica": JurisprudenciaSource(
        seeds=(
            Seed("STJ", "202001090402", "REsp 1873811"),  # Tema Repetitivo 1210, core (CC art. 50)
            Seed("STF", "sjur550030", 'titulo:"RE 1387795"'),  # Tema 1232, tangential
        ),
        searches={
            "STF": "desconsideração personalidade jurídica art. 50 código civil",
            "STJ": "desconsideração personalidade jurídica art. 50",
        },
    ),
}


@dataclass
class JurisprudenciaReport:
    ingested: int = 0
    references: int = 0  # `rule` REFERENCES edges from decisions to the dispositivos they cite
    unresolved: int = 0  # decisions with a citation no rule resolved (left for the LLM)
    failed: dict[str, str] = field(default_factory=dict)  # seed id or court -> reason
    enrichment: dict[str, EnrichmentCounts] = field(default_factory=dict)  # court -> LLM phase
    dropped: dict[str, int] = field(default_factory=dict)  # court -> items failing validation
    out_of_vocabulary: dict[str, list[str]] = field(default_factory=dict)  # court -> proposed ids

    def render(self) -> str:
        lines = [
            f"ingested {self.ingested} jurisprudência nodes, {self.references} references, "
            f"{self.unresolved} decisions with unresolved citations"
        ]
        lines += [
            f"enriched {court}: {c.processed} processed, {c.empty} empty, {c.too_long} too long, "
            f"{c.kept} kept, {c.returned} returned to pending, {c.left_pending} left pending, "
            f"{self.dropped.get(court, 0)} dropped"
            for court, c in self.enrichment.items()
        ]
        lines += [
            f"out of vocabulary {court}: {', '.join(sorted(set(ids)))}"
            for court, ids in self.out_of_vocabulary.items()
            if ids
        ]
        lines += [f"failed {key}: {reason}" for key, reason in self.failed.items()]
        return "\n".join(lines)


def ingest_jurisprudencia(
    fetchers: dict[str, JurisprudenciaFetcher],
    store: GraphStore,
    source: JurisprudenciaSource,
    enrichment: EnrichConfig | None = None,
    resolver: UrnResolver | None = None,
) -> JurisprudenciaReport:
    report = JurisprudenciaReport()
    items: dict[str, Jurisprudencia] = {}
    for seed in source.seeds:
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
    for court, query in source.searches.items() if source.top_hits > 0 else ():
        try:
            for hit in fetchers[court].search(query, source.top_hits)[: source.top_hits]:
                items.setdefault(hit.id, hit)
        except Exception as error:
            report.failed[court] = str(error)
    if items:
        relations: list[Relation] = []
        for j in items.values():
            extraction = extract_decision_relations(j, resolver)
            relations += extraction.relations
            report.unresolved += extraction.needs_enrichment
        store.write_jurisprudencia(list(items.values()), relations)
        report.references = len(relations)
    report.ingested = len(items)
    if enrichment:
        _enrich(list(items.values()), store, enrichment, report)
    return report


def _enrich(
    items: list[Jurisprudencia],
    store: GraphStore,
    config: EnrichConfig,
    report: JurisprudenciaReport,
) -> None:
    """Send each pending decision to `enrich_decision`, record the outcome and replace its `llm`
    edges. The records are grouped by court. A reply that cannot be read leaves that decision
    pending; an exhausted provider stops the calls and leaves the rest pending."""
    limits = (
        {} if config.max_input_tokens is None else {"max_input_tokens": config.max_input_tokens}
    )
    exhausted = False
    for court in sorted({j.court for j in items}):
        counts = report.enrichment[court] = EnrichmentCounts()
        decisions = [j for j in items if j.court == court]
        keys = {
            j.id: enrichment_key(
                "\n".join(decision_texts(j)),
                config.vocabulary,
                config.lock,
                prompt=DECISION_PROMPT,
            )
            for j in decisions
        }
        stored = config.metadata.records(court)
        pending = set(config.metadata.pending(court, keys))
        counts.kept = len(decisions) - len(pending)
        for j in decisions:
            if j.id not in pending:
                continue
            record = EnrichmentRecord(j.id, court, keys[j.id], EnrichmentStatus.PENDING)
            try:
                result = (
                    None
                    if exhausted
                    else enrich_decision(
                        j, config.vocabulary, config.provider, config.lock, **limits
                    )
                )
            except ProviderError:
                result = None
            if result is None or result.failed:
                exhausted = exhausted or result is None
                counts.left_pending += 1
                config.metadata.record(record)
                continue
            store.replace_llm_relations(j.id, result.relations)
            config.metadata.record(
                EnrichmentRecord(
                    j.id, court, keys[j.id], EnrichmentStatus.OK, result.dropped, result.skipped
                )
            )
            report.dropped[court] = report.dropped.get(court, 0) + result.dropped
            report.out_of_vocabulary.setdefault(court, []).extend(result.out_of_vocabulary)
            if result.skipped:
                if result.skipped == "too_long":
                    counts.too_long += 1
                else:
                    counts.empty += 1
                continue
            counts.processed += 1
            if (before := stored.get(j.id)) and before.status is EnrichmentStatus.OK:
                counts.returned += 1
