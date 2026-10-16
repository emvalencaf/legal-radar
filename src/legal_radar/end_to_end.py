"""One run over an assunto: ingest the leis and decisions, (enrich), export the seed, answer a
query, score the question set and write the report. The CLI and the top-seam test both call it."""

from dataclasses import dataclass
from pathlib import Path

from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
from legal_radar.adapters.neo4j_seed import export_seed
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.adapters.prompt_lock import default_lock
from legal_radar.answer_evaluation import QUESTION_PATHS, System, UsageMeter, load_questions
from legal_radar.application.answer import CitedAnswer, ask
from legal_radar.application.assunto import AssuntoResolver
from legal_radar.application.ingest import EnrichConfig, IngestionReport, ingest
from legal_radar.application.jurisprudencia import (
    JURISPRUDENCIA,
    JurisprudenciaReport,
    ingest_jurisprudencia,
)
from legal_radar.application.ports import JurisprudenciaFetcher, PageSource, Provider
from legal_radar.assayer_harness import RUNS_DIR, Report
from legal_radar.domain.anchors import ANCHORS
from legal_radar.domain.prompts import PromptLock
from legal_radar.eval_runner import run_systems
from legal_radar.report import build_report


@dataclass
class EndToEndResult:
    ingestion: IngestionReport
    jurisprudencia: JurisprudenciaReport
    answer: CitedAnswer
    evaluations: list[Report]
    report_path: Path
    seed_path: Path | None = None


def run_end_to_end(
    assunto: str,
    *,
    lexml: PageSource,
    planalto: PageSource,
    fetchers: dict[str, JurisprudenciaFetcher],
    store: Neo4jGraphStore,
    provider: Provider,
    report_out: Path,
    runs_dir: Path = RUNS_DIR,
    seed_out: Path | None = None,
    lei_enrichment: EnrichConfig | None = None,
    decision_enrichment: EnrichConfig | None = None,
    lock: PromptLock | None = None,
) -> EndToEndResult:
    """Builds the graph of `assunto`, then answers its name as a query, scores its question set
    (the graph system) into `runs_dir` and writes the static report to `report_out`."""
    lock = lock or default_lock()
    ingestion = ingest(ANCHORS[assunto], lexml, planalto, store, enrichment=lei_enrichment)
    jurisprudencia = ingest_jurisprudencia(
        fetchers, store, JURISPRUDENCIA[assunto], enrichment=decision_enrichment
    )
    if seed_out:
        seed_out.parent.mkdir(parents=True, exist_ok=True)
        seed_out.write_text(export_seed(store.driver), encoding="utf-8")
    meter = UsageMeter(provider)
    reader, resolve = Neo4jGraphReader(store.driver), AssuntoResolver(meter).resolve
    answer = ask(assunto, resolve, reader, meter, lock)
    evaluations = run_systems(
        [(System(), lambda query: ask(query, resolve, reader, meter, lock))],
        load_questions(QUESTION_PATHS[assunto]),
        meter,
        lock,
        runs_dir=runs_dir,
    )
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(build_report(runs_dir, lock), encoding="utf-8")
    return EndToEndResult(ingestion, jurisprudencia, answer, evaluations, report_out, seed_out)
