"""One run over an subject: ingest the statutes and decisions, (enrich), export the seed, answer a
query, score the question set and write the report. The CLI and the top-seam test both call it."""

from dataclasses import dataclass
from pathlib import Path

from legal_radar.adapters.assayer.harness import RUNS_DIR, Report
from legal_radar.adapters.assayer.runner import run_systems
from legal_radar.adapters.neo4j_reader import Neo4jGraphReader
from legal_radar.adapters.neo4j_seed import export_seed
from legal_radar.adapters.neo4j_store import Neo4jGraphStore
from legal_radar.adapters.prompt_lock import default_lock
from legal_radar.application.answer import CitedAnswer, ask
from legal_radar.application.case_law import (
    CASE_LAW,
    CaseLawReport,
    ingest_case_law,
)
from legal_radar.application.evaluation.answers import (
    QUESTION_PATHS,
    System,
    UsageMeter,
    load_questions,
)
from legal_radar.application.evaluation.report import build_report
from legal_radar.application.ingest import EnrichConfig, IngestionReport, ingest
from legal_radar.application.ports import (
    CaseLawFetcher,
    Provider,
    StatuteLocator,
    StatuteTextSource,
)
from legal_radar.application.subject import SubjectResolver
from legal_radar.domain.anchors import ANCHORS
from legal_radar.domain.prompts import PromptLock


@dataclass
class EndToEndResult:
    ingestion: IngestionReport
    case_law: CaseLawReport
    answer: CitedAnswer
    evaluations: list[Report]
    report_path: Path
    seed_path: Path | None = None


def run_end_to_end(
    subject: str,
    *,
    locator: StatuteLocator,
    texts: StatuteTextSource,
    fetchers: dict[str, CaseLawFetcher],
    store: Neo4jGraphStore,
    provider: Provider,
    report_out: Path,
    runs_dir: Path = RUNS_DIR,
    seed_out: Path | None = None,
    statute_enrichment: EnrichConfig | None = None,
    decision_enrichment: EnrichConfig | None = None,
    lock: PromptLock | None = None,
) -> EndToEndResult:
    """Builds the graph of `assunto`, then answers its name as a query, scores its question set
    (the graph system) into `runs_dir` and writes the static report to `report_out`."""
    lock = lock or default_lock()
    ingestion = ingest(ANCHORS[subject], locator, texts, store, enrichment=statute_enrichment)
    case_law = ingest_case_law(fetchers, store, CASE_LAW[subject], enrichment=decision_enrichment)
    if seed_out:
        seed_out.parent.mkdir(parents=True, exist_ok=True)
        seed_out.write_text(export_seed(store.driver), encoding="utf-8")
    meter = UsageMeter(provider)
    reader, resolve = Neo4jGraphReader(store.driver), SubjectResolver(meter).resolve
    answer = ask(subject, resolve, reader, meter, lock)
    evaluations = run_systems(
        [(System(), lambda query: ask(query, resolve, reader, meter, lock))],
        load_questions(QUESTION_PATHS[subject]),
        meter,
        lock,
        runs_dir=runs_dir,
    )
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(build_report(runs_dir, lock), encoding="utf-8")
    return EndToEndResult(ingestion, case_law, answer, evaluations, report_out, seed_out)
