"""Lei ingestion: LexML URN -> Planalto page -> legal-document AST -> graph."""

from dataclasses import dataclass, field, replace

from legal_radar.anchors import AnchorLei
from legal_radar.concepts import Vocabulary
from legal_radar.domain import (
    Dispositivo,
    EnrichmentRecord,
    EnrichmentStatus,
    GraphBatch,
    Lei,
    Relation,
)
from legal_radar.enricher import Enrichment, ancestors_of, candidate_targets, enrich, triage
from legal_radar.enrichment import enrichment_key
from legal_radar.lexml import LexmlError, resolve_urn, search_urn
from legal_radar.llm import ProviderError
from legal_radar.planalto import parse_planalto
from legal_radar.ports import GraphStore, MetadataStore, PageSource, Provider
from legal_radar.prompts import PromptLock
from legal_radar.relations import Extraction, UrnResolver, extract_relations


@dataclass(frozen=True)
class EnrichConfig:
    """What `ingest --enrich` needs to send the chunks the rules left to the LLM."""

    vocabulary: Vocabulary
    provider: Provider
    metadata: MetadataStore
    lock: PromptLock | None = None
    max_input_tokens: int | None = None


@dataclass
class EnrichmentCounts:
    processed: int = 0  # sent to the LLM and recorded `ok`
    too_long: int = 0  # recorded `ok` without a call: the prompt exceeds the input ceiling
    kept: int = 0  # `ok` with an unchanged key: not sent
    returned: int = 0  # `ok` before, back to pending because the key changed
    left_pending: int = 0  # still pending after this run


@dataclass
class IngestionReport:
    ingested: dict[str, int] = field(default_factory=dict)  # urn -> dispositivo count
    skipped: dict[str, list[str]] = field(default_factory=dict)  # urn -> non-Planalto hosts
    failed: dict[str, str] = field(default_factory=dict)  # keyword -> reason
    relations: dict[str, int] = field(default_factory=dict)  # urn -> edges extracted by rules
    needs_llm: dict[str, int] = field(default_factory=dict)  # urn -> chunks left for the enricher
    dropped: dict[str, int] = field(default_factory=dict)  # urn -> items failing validation
    enrichment: dict[str, EnrichmentCounts] = field(default_factory=dict)  # urn -> LLM phase

    def render(self) -> str:
        lines = [
            f"ingested {urn}: {n} dispositivos, {self.relations.get(urn, 0)} relations, "
            f"{self.needs_llm.get(urn, 0)} for the LLM, {self.dropped.get(urn, 0)} dropped"
            for urn, n in self.ingested.items()
        ]
        lines += [
            f"enriched {urn}: {c.processed} processed, {c.too_long} too long, {c.kept} kept, "
            f"{c.returned} returned to pending, {c.left_pending} left pending"
            for urn, c in self.enrichment.items()
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
    enrichment: EnrichConfig | None = None,
) -> IngestionReport:
    """Parse every anchor lei, extract its relations, then load them.

    Relations are extracted once all leis are parsed: a citation of a lei of this run is checked
    against its dispositivos, and one of any other lei is a stub (LOW).

    With `enrichment`, each lei is loaded with its rule-derived edges first; then the chunks the
    rules left for the LLM that are `pending` are sent to it, one by one.
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
    extractions: dict[str, Extraction] = {}
    for lei, dispositivos in parsed:
        relations: list[Relation] = []
        for d in dispositivos:
            extraction = extractions[d.id] = extract_relations(d, resolver, in_graph)
            relations += extraction.relations
            report.needs_llm[lei.id] = report.needs_llm.get(lei.id, 0) + extraction.needs_enrichment
            report.dropped[lei.id] = report.dropped.get(lei.id, 0) + extraction.dropped
        store.write(GraphBatch(lei, dispositivos, [], [], relations))
        report.ingested[lei.id] = len(dispositivos)
        report.relations[lei.id] = len(relations)
    if enrichment:
        _enrich(parsed, extractions, store, enrichment, report)
    return report


def _enrich(
    parsed: list[tuple[Lei, list[Dispositivo]]],
    extractions: dict[str, Extraction],
    store: GraphStore,
    config: EnrichConfig,
    report: IngestionReport,
) -> None:
    """Send each pending LLM-bound chunk to `enrich`, record the outcome and replace its `llm`
    edges. A reply that cannot be read leaves that chunk pending; an exhausted provider stops the
    calls and leaves the rest pending. `returned` counts the chunks that were `ok` under an older
    key and are `ok` again under the current one, so it is a subset of `processed`. A `too_long`
    chunk is recorded `ok`, so it is not retried forever, but it is counted apart."""
    exhausted = False
    for lei, dispositivos in parsed:
        counts = report.enrichment[lei.id] = EnrichmentCounts()
        by_id = {d.id: d for d in dispositivos}
        candidates = candidate_targets(dispositivos)
        chunks = [
            d for d in dispositivos if extractions[d.id].needs_enrichment and triage(d) is None
        ]
        keys = {d.id: enrichment_key(d.text, config.vocabulary, config.lock) for d in chunks}
        stored = config.metadata.records(lei.id)
        pending = set(config.metadata.pending(lei.id, keys))
        counts.kept = len(chunks) - len(pending)
        for d in chunks:
            # the rules write their unresolved citations on every run: forget the grounded ones
            if d.id not in pending and stored[d.id].resolved:
                store.resolve_citations(d.id, list(stored[d.id].resolved))
        for d in chunks:
            if d.id not in pending:
                continue
            if exhausted:
                counts.left_pending += 1
                continue
            outcome = _enrich_chunk(d, lei, extractions[d.id], by_id, candidates, config)
            if outcome is None:  # the provider is exhausted: this chunk and the rest stay pending
                exhausted = True
                counts.left_pending += 1
                config.metadata.record(
                    EnrichmentRecord(d.id, lei.id, keys[d.id], EnrichmentStatus.PENDING)
                )
            elif outcome.failed:
                counts.left_pending += 1
                config.metadata.record(
                    EnrichmentRecord(d.id, lei.id, keys[d.id], EnrichmentStatus.PENDING)
                )
            else:
                resolved = [r.unresolved for r in outcome.resolved if r.unresolved]
                store.replace_llm_relations(d.id, outcome.relations)
                store.resolve_citations(d.id, resolved)
                config.metadata.record(
                    EnrichmentRecord(
                        d.id,
                        lei.id,
                        keys[d.id],
                        EnrichmentStatus.OK,
                        outcome.dropped,
                        outcome.skipped,
                        tuple(resolved),
                    )
                )
                if outcome.skipped == "too_long":
                    counts.too_long += 1
                    continue
                counts.processed += 1
                if (before := stored.get(d.id)) and before.status is EnrichmentStatus.OK:
                    counts.returned += 1
                report.dropped[lei.id] = report.dropped.get(lei.id, 0) + outcome.dropped


def _enrich_chunk(
    d: Dispositivo,
    lei: Lei,
    extraction: Extraction,
    by_id: dict[str, Dispositivo],
    candidates: list[str],
    config: EnrichConfig,
) -> Enrichment | None:
    """The enrichment of one chunk with the edges the rules already hold left out, or None when
    the provider is exhausted."""
    limits = (
        {} if config.max_input_tokens is None else {"max_input_tokens": config.max_input_tokens}
    )
    try:
        result = enrich(
            d,
            config.vocabulary,
            config.provider,
            config.lock,
            ancestors=ancestors_of(d, by_id),
            unresolved=[r for r in extraction.relations if r.unresolved],
            candidates=candidates,
            **limits,
        )
    except ProviderError:
        return None
    held = {(r.type, r.source_id, r.target_id) for r in extraction.relations}
    fresh = [r for r in result.relations if (r.type, r.source_id, r.target_id) not in held]
    return replace(result, relations=fresh)
